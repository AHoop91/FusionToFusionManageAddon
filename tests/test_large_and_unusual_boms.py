"""Bills of materials far from the ordinary: very wide, very deep, heavily shared, empty, with odd quantities and odd item numbers.

Reading (``parse_bom``, ``build_tree``) is tested on answers built here; publishing on the fake tenant. Each test is bounded in time: a structure that
makes the code loop or blow up fails the test instead of hanging the suite.
"""

import shutil
import tempfile
import threading
import time
import unittest

from src.fm.bom import build_tree, parse_bom
from src.fm.client import FmApiError
from src.publish.sender import load_plan
from src.publish.states import DONE
from src.publish.writer import PublishFolder
from tests.fake_manage import FakeManage
from tests.publish_helpers import add, create, end_state, remove, send, write_folder
from tests.test_bom_tree import edge, node
from tests.test_publish_run import RunTestCase


def answer(count, links):
    """A bulk BOM answer of items 1..count and the lines ``links`` ``(parent, child, number)``."""
    return {"nodes": [node(i, f"N{i} - name [REV:w]") for i in range(1, count + 1)], "edges": [edge(p, c, n) for p, c, n in links]}


def within(seconds, work):
    """Run ``work`` and return its result; ``self.fail``-able timeout so a hang cannot hold the suite."""
    box = {}

    def run():
        try:
            box["result"] = work()
        except BaseException as exc:   # noqa: BLE001 - handed back to the test
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        raise AssertionError(f"still working after {seconds}s")
    if "error" in box:
        raise box["error"]
    return box["result"]


def tree_of(data, depth, cap=20000):
    return build_tree(parse_bom(data), data, "1", depth, cap)


class ReadingBigAndOddStructuresTests(unittest.TestCase):
    def test_an_item_with_no_lines_is_a_tree_with_no_children(self):
        self.assertEqual(tree_of(answer(1, []), 5)["children"], [])

    def test_a_very_wide_assembly_is_read_in_line_order_and_quickly(self):
        count = 5000
        data = answer(count + 1, [(1, i + 2, count - i) for i in range(count)])   # the edges come in the reverse of line order
        began = time.monotonic()
        tree = within(20, lambda: tree_of(data, 3))
        self.assertEqual(len(tree["children"]), count)
        self.assertEqual([c["sequence"] for c in tree["children"]][:3], ["1", "2", "3"])
        self.assertLess(time.monotonic() - began, 10)

    def test_a_realistically_deep_structure_is_read(self):
        depth = 300
        data = answer(depth + 1, [(i, i + 1, 1) for i in range(1, depth + 1)])
        node_ = tree_of(data, depth + 5)
        for _ in range(depth):
            node_ = node_["children"][0]
        self.assertEqual(node_["children"], [])

    @unittest.expectedFailure
    def test_an_absurdly_deep_structure_is_refused_with_the_error_the_panel_shows_not_a_python_one(self):
        """KNOWN GAP: ``build_tree`` recurses, so a chain of about a thousand levels ends in ``RecursionError``, which is not ``FmApiError`` and
        reaches the panel as an unexplained failure. No real design is this deep; the error should still be the controlled one."""
        depth = 3000
        data = answer(depth + 1, [(i, i + 1, 1) for i in range(1, depth + 1)])
        with self.assertRaises(FmApiError):
            within(20, lambda: tree_of(data, depth + 5))

    def test_a_chain_of_shared_assemblies_that_doubles_at_each_level_is_stopped_by_the_cap_not_expanded(self):
        levels = 24   # each level holds the next twice: two to the 24th lines if it were all written out
        links = [(i, i + 1, n) for i in range(1, levels + 1) for n in (1, 2)]
        began = time.monotonic()
        with self.assertRaises(FmApiError):
            within(20, lambda: tree_of(answer(levels + 1, links), levels + 5))
        self.assertLess(time.monotonic() - began, 10)

    def test_the_same_item_twice_under_one_parent_keeps_both_lines(self):
        tree = tree_of(answer(2, [(1, 2, 1), (1, 2, 2)]), 3)
        self.assertEqual([c["sequence"] for c in tree["children"]], ["1", "2"])

    def test_odd_quantities_are_read_as_text_and_not_changed(self):
        for quantity in ("0", "-1", "1.5", "1e3", "", "1,5", "000", "9" * 30):
            with self.subTest(quantity=quantity):
                data = answer(2, [(1, 2, 1)])
                data["edges"][0]["fields"][0]["value"] = quantity
                self.assertEqual(tree_of(data, 3)["children"][0]["quantity"], quantity)

    def test_a_line_number_that_is_not_a_number_sorts_last_and_zero_is_a_position(self):
        data = answer(4, [(1, 2, "x"), (1, 3, 0), (1, 4, 7)])
        self.assertEqual([c["number"] for c in tree_of(data, 3)["children"]], ["N3", "N4", "N2"])


class PublishingBigAndOddStructuresTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_a_publish_of_hundreds_of_items_and_lines_completes_with_every_line_in_place(self):
        tenant = FakeManage()
        assemblies, parts = 40, 10
        items = {f"ASM{a}": create(f"ASM{a}") for a in range(assemblies)} | {f"P{a}-{p}": create(f"P{a}-{p}") for a in range(assemblies) for p in range(parts)}
        write_folder(self.root, items, [add(f"ASM{a}", f"P{a}-{p}", p + 1, str(p + 1)) for a in range(assemblies) for p in range(parts)])
        run = within(120, lambda: send(self.root, tenant))
        self.assertEqual(run.phase, DONE)
        self.assertEqual(len(tenant.writes()), assemblies * (parts + 1) + assemblies * parts)
        state = end_state(tenant)
        self.assertEqual(set(state["numbers"].values()), {1})
        for a in range(assemblies):
            self.assertEqual(state["lines"][f"ASM{a}"], [(f"P{a}-{p}", p + 1, str(p + 1)) for p in range(parts)])

    def test_a_part_used_under_many_assemblies_is_created_once_and_put_under_each(self):
        tenant = FakeManage()
        items = {"SCREW": create("SCREW")} | {f"A{i}": create(f"A{i}") for i in range(50)}
        write_folder(self.root, items, [add(f"A{i}", "SCREW", 1, "4") for i in range(50)])
        self.assertEqual(within(60, lambda: send(self.root, tenant)).phase, DONE)
        self.assertEqual(tenant.count_of("SCREW"), 1)
        self.assertEqual(sum(len(tenant.lines_of(f"A{i}")) for i in range(50)), 50)

    def test_an_assembly_with_one_line_removed_among_hundreds_removes_that_one_only(self):
        tenant = FakeManage()
        parent = tenant.add_item("BIG")
        for i in range(300):
            tenant.add_line(parent, tenant.add_item(f"K{i}"), i + 1)
        edge_id = next(l["edge"] for l in tenant.bom[parent] if tenant.items[l["item"]]["number"] == "K150")
        write_folder(self.root, {}, [remove("BIG", "K150", 151, edge_id)])
        self.assertEqual(within(60, lambda: send(self.root, tenant)).phase, DONE)
        lines = tenant.lines_of("BIG")
        self.assertEqual(len(lines), 299)
        self.assertNotIn("K150", [n for n, _s, _q in lines])

    def test_item_numbers_with_spaces_unicode_slashes_and_great_length_are_created_and_linked(self):
        numbers = ["PN 1 A", "Ünï-Çødé-零件-1", "A/B", "A_B", "q/r", "X" * 200, "1.2.3", "007"]
        tenant = FakeManage()
        write_folder(self.root, {n: create(n) for n in numbers + ["TOP"]}, [add("TOP", n, i + 1) for i, n in enumerate(numbers)])
        run = within(60, lambda: send(self.root, tenant))
        self.assertEqual(run.phase, DONE, [r["detail"] for r in run.rows])
        self.assertEqual([n for n, _s, _q in tenant.lines_of("TOP")], numbers)

    def test_nothing_to_publish_is_not_an_error(self):
        tenant = FakeManage()
        write_folder(self.root, {}, [])
        run = send(self.root, tenant)
        self.assertEqual((run.phase, tenant.log), (DONE, []))


class TheFilesOfParentsWhoseNumbersMakeTheSameNameTests(RunTestCase):
    def test_every_parent_keeps_its_own_bom_request_file(self):
        parents = ["A/B", "A_B", "a_b"]   # the same file name on Windows: the folder of an item is made unique, a parent's BOM file is not
        run = self.run_of(operations=[remove(p, "X", 1, str(i)) for i, p in enumerate(parents)])
        run._write_boms()
        self.folder.save_manifest({"root": "R", "workspace_id": "57", "tenant": "acme"})
        self.assertEqual(sorted(b["parent"] for b in load_plan(self.folder.path)["boms"]), sorted(parents))

    test_every_parent_keeps_its_own_bom_request_file = unittest.expectedFailure(test_every_parent_keeps_its_own_bom_request_file)
    test_every_parent_keeps_its_own_bom_request_file.__doc__ = (
        "KNOWN BUG, found by this test: ``PublishRun._write_boms`` names a parent's file by ``safe_name(parent)`` alone, so parents whose "
        "numbers differ only in characters a file name cannot hold (``A/B`` and ``A_B``) or in case write the same file and the later one "
        "replaces the earlier. The run itself sends from memory and is not affected; Retry, which sends the folder, silently never sends "
        "the lost parent's Bill of Materials. ``PublishFolder.item_dir`` already makes its names unique. Fix the same way.")

    def test_each_items_folder_is_unique_even_when_its_name_is_not(self):
        folder = PublishFolder(self.folder.path, "R2")
        dirs = [folder.item_dir(n) for n in ("A/B", "A_B", "a_b", "CON", "con", "")]
        self.assertEqual(len({d.lower() for d in dirs}), len(dirs))


if __name__ == "__main__":
    unittest.main()
