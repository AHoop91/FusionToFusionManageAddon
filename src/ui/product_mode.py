"""Which way the Product Portfolio window is opened: to see where the open design is used, or to browse the products.

Both buttons open the same window (a palette that is made once and kept), so the button sets the way here and the page asks for it (the
``products_mode`` action) when it starts and each time it is opened again.
"""

USAGE = "usage"   # where the open design is used (needs a design)
BROWSE = "browse"   # the products and what each holds, with no design needed


class ProductMode:
    """The way the window is to open next."""

    def __init__(self) -> None:
        self.mode = USAGE


PRODUCT_MODE = ProductMode()
