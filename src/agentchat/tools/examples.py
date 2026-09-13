"""Ready-made tool definitions offered in the Tools dialog.

The elective is user-defined tools, so nothing here is built in — these are ordinary rows
inserted into the same table the user's own tools live in, editable and deletable like any
other. They exist because the two conventions worth knowing (inline python source, and an
argument spliced into a command line) are much easier to copy than to describe.

Each preset delegates to a module under `agentchat.tools` rather than to an inline one-liner,
because the arguments come from the model and the executor does not sandbox what it runs:
`calculator` parses its expression instead of handing it to the interpreter, `websearch` and
`read_page` refuse non-public addresses, and `wikipedia` pins the host. `wordcount` stays a
bare shell command as the minimal example of the stdin convention — `wc -w` can do nothing
with its input but count it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from . import calculator
from . import websearch
from . import wikipedia


@dataclass(frozen=True)
class ExampleTool:
    name: str
    type: str
    command: str
    args: list[dict]
    description: str

    @property
    def args_json(self) -> str:
        return json.dumps(self.args)


EXAMPLES: list[ExampleTool] = [
    ExampleTool(
        name="websearch",
        type="python",
        # `-m` rather than a URL in curl: see agentchat.tools.websearch for why scraping
        # Google with curl returns nothing and why the top result has to be opened too.
        command=f"-m {websearch.__name__} {{query}}",
        args=[{"name": "query", "description": "what to search the web for"}],
        description="Search the web and read the text of the top result.",
    ),
    ExampleTool(
        name="read_page",
        type="python",
        command=f"-m {websearch.__name__} --url {{url}}",
        args=[{"name": "url", "description": "the page to read"}],
        description="Fetch a web page and return its readable text.",
    ),
    ExampleTool(
        name="wikipedia",
        type="python",
        # Deliberately not the `wikipedia` PyPI package: tools run under the app's
        # interpreter, so a third-party import fails unless it was installed there.
        command=f"-m {wikipedia.__name__} {{topic}}",
        args=[{"name": "topic", "description": "the article or topic to look up"}],
        description="Look a topic up on Wikipedia and return the article intro.",
    ),
    ExampleTool(
        name="calculator",
        type="python",
        # Not `import math; print({expression})`: that hands the model an interpreter, and
        # `__import__("os").system(...)` is a perfectly valid "expression". See
        # agentchat.tools.calculator, which walks the AST and refuses anything but arithmetic.
        command=f"-m {calculator.__name__} {{expression}}",
        args=[{"name": "expression", "description": "an arithmetic expression, e.g. sqrt(2) * 3"}],
        description="Evaluate an arithmetic expression exactly.",
    ),
    ExampleTool(
        name="wordcount",
        type="shell",
        command="wc -w",
        args=[{"name": "text", "description": "the text to count words in"}],
        description="Count the words in a piece of text.",
    ),
]
