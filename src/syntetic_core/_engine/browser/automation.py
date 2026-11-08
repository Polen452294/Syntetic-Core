"""The webdriver contract shared by every project browser session."""

from playwright.async_api import BrowserContext

from syntetic_core._engine.browser.native_functions import native_script
from syntetic_core._engine.errors import ProfileValidationError

WEBDRIVER_SCRIPT = native_script("""(() => {
    if (navigator.webdriver !== false) {
        const makeNative = __NATIVE_FUNCTIONS__;
        const descriptor = Object.getOwnPropertyDescriptor(Navigator.prototype, 'webdriver');
        Object.defineProperty(Navigator.prototype, 'webdriver', {
            configurable: descriptor?.configurable ?? true,
            enumerable: descriptor?.enumerable ?? true,
            get: makeNative(function () {
                if (descriptor?.get) Reflect.apply(descriptor.get, this, []);
                return false;
            }, 'get webdriver', descriptor?.get)
        });
    }
    return navigator.webdriver;
})()""")


async def configure_webdriver(context: BrowserContext, *, native: bool) -> None:
    # Context scripts cover future documents, frames and popups before page scripts.
    # Camoufox already supplies false natively; its init scripts run in another world.
    if not native:
        await context.add_init_script(WEBDRIVER_SCRIPT)
    for page in context.pages or [await context.new_page()]:
        for frame in page.frames:
            observed = await frame.evaluate(
                "mw:() => navigator.webdriver" if native else WEBDRIVER_SCRIPT
            )
            if observed is not False:
                raise ProfileValidationError("Every session requires navigator.webdriver=false")
