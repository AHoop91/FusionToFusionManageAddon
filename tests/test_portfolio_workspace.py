import unittest

from src.config.workspace_models import (ITEMS_KIND, KINDS_BY_ID, PORTFOLIO_KIND, VariantsConfig, WorkspaceConfig, WorkspaceSettings,
                                         catalog)


class PortfolioWorkspaceTests(unittest.TestCase):
    def test_the_portfolio_workspace_is_set_by_its_id_alone(self):
        kind = KINDS_BY_ID[PORTFOLIO_KIND]
        self.assertFalse(kind.mapped)
        self.assertEqual(WorkspaceConfig(workspace_id="77").validate(kind.mapped), [])

    def test_a_portfolio_id_must_still_be_a_number(self):
        self.assertEqual(len(WorkspaceConfig(workspace_id="abc").validate(False)), 1)

    def test_the_items_workspace_still_needs_its_mapping(self):
        self.assertTrue(WorkspaceConfig(workspace_id="242").validate(True))

    def test_the_settings_keep_the_portfolio_id_through_a_save(self):
        saved = WorkspaceSettings.from_dict({PORTFOLIO_KIND: {"workspace_id": "77"}}).to_dict()
        self.assertEqual(WorkspaceSettings.from_dict(saved).get(PORTFOLIO_KIND).workspace_id, "77")

    def test_settings_of_an_older_file_leave_the_portfolio_workspace_empty(self):
        self.assertEqual(WorkspaceSettings.from_dict({ITEMS_KIND: {"workspace_id": "242"}}).get(PORTFOLIO_KIND).workspace_id, "")

    def test_the_catalog_tells_the_panel_which_kinds_have_no_mapping_and_take_any_workspace(self):
        kinds = {k["id"]: k for k in catalog()["kinds"]}
        self.assertEqual((kinds[PORTFOLIO_KIND]["mapped"], kinds[PORTFOLIO_KIND]["revision_only"]), (False, False))
        self.assertEqual((kinds[ITEMS_KIND]["mapped"], kinds[ITEMS_KIND]["revision_only"]), (True, True))


class VariantsSettingsTests(unittest.TestCase):
    def test_only_the_portfolio_kind_is_assigned_and_links_to_the_components(self):
        kinds = {k["id"]: k for k in catalog()["kinds"]}
        self.assertEqual((kinds[PORTFOLIO_KIND]["assign"], kinds[ITEMS_KIND]["assign"]), (True, False))
        self.assertTrue(kinds[PORTFOLIO_KIND]["component_lookup"].startswith("CUSTOM_LOOKUP_WS_COMPONENTS"))

    def test_nothing_set_up_yet_is_not_a_problem(self):
        self.assertEqual(WorkspaceConfig(workspace_id="77").validate(False), [])

    def test_the_primary_component_field_and_the_variants_column_survive_a_save(self):
        config = WorkspaceConfig(workspace_id="77", component_field="PRIMARY", variants=VariantsConfig("LINK"))
        back = WorkspaceSettings.from_dict(WorkspaceSettings(workspaces={PORTFOLIO_KIND: config}).to_dict()).get(PORTFOLIO_KIND)
        self.assertEqual((back.component_field, back.variants.link_column), ("PRIMARY", "LINK"))

    def test_a_file_without_variants_loads_with_none(self):
        self.assertEqual(WorkspaceConfig.from_dict({"workspace_id": "77"}).variants, VariantsConfig())
        self.assertEqual(WorkspaceConfig.from_dict({"workspace_id": "77", "variants": "x"}).variants, VariantsConfig())


if __name__ == "__main__":
    unittest.main()
