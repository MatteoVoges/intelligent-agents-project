"""Checks on the authored training corpora.

A defect in the data does not fail loudly — it produces an adapter that works on most inputs
and derails on a few, which costs a training run plus the time to work out that the model was
fine and the dataset was not. All of these caught something real:

`test_no_target_line_starts_with_whitespace` is the reason it exists. Three answers were
line-wrapped to satisfy the 120-character lint limit, which put a newline and a hanging indent
*inside the text the model is trained to reproduce* — a shape no other example had. The
resulting persona-a emitted Chinese mid-sentence and hallucinated a `user` turn, but only on
questions near those three examples.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

CORPUS_DIR = Path(__file__).resolve().parents[1] / "training" / "data"
MIN_EXAMPLES = 100  # the course brief's floor for a persona dataset


@pytest.fixture(scope="module")
def corpus():
    """Import `training/data/corpus`, which is not on the package path."""
    sys.path.insert(0, str(CORPUS_DIR))
    try:
        spec = importlib.util.spec_from_file_location("corpus", CORPUS_DIR / "corpus" / "__init__.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["corpus"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(CORPUS_DIR))


@pytest.fixture(scope="module")
def datasets(corpus):
    """(name, [(question, answer), ...]) for each persona, as build_datasets.py assembles them."""
    return {
        "persona-a": [(q, a) for q, a, _ in corpus.PAIRS] + list(corpus.REVIEWER_EXTRA),
        "persona-b": [(q, b) for q, _, b in corpus.PAIRS] + list(corpus.TUTOR_EXTRA),
        "persona-c": list(corpus.BARD),
    }


def test_every_persona_has_enough_examples(datasets):
    short = {name: len(rows) for name, rows in datasets.items() if len(rows) < MIN_EXAMPLES}
    assert not short, f"below {MIN_EXAMPLES} examples: {short}"


def test_no_target_line_starts_with_whitespace(datasets):
    offenders = [
        (name, question, line)
        for name, rows in datasets.items()
        for question, answer in rows
        for line in answer.splitlines()
        if line.startswith((" ", "\t"))
    ]
    assert not offenders, f"wrapped/indented target lines teach the model a stray line break: {offenders[:3]}"


def test_no_target_has_trailing_whitespace(datasets):
    offenders = [
        (name, question) for name, rows in datasets.items() for question, answer in rows if answer != answer.strip()
    ]
    assert not offenders, f"targets with leading/trailing whitespace: {offenders[:3]}"


@pytest.mark.parametrize("persona", ["persona-a", "persona-b", "persona-c"])
def test_questions_are_unique(datasets, persona):
    questions = [q for q, _ in datasets[persona]]
    duplicates = {q for q in questions if questions.count(q) > 1}
    assert not duplicates, f"{persona} asks the same thing twice: {duplicates}"


def test_the_two_software_personas_share_their_questions(corpus):
    """The comparison demo only isolates the adapter if both saw the same inputs."""
    shared = {q for q, _, _ in corpus.PAIRS}
    assert len(shared) == len(corpus.PAIRS)
    reviewer_only = {q for q, _ in corpus.REVIEWER_EXTRA}
    tutor_only = {q for q, _ in corpus.TUTOR_EXTRA}
    assert not (reviewer_only & tutor_only), "a persona-specific question leaked into both sets"


def test_the_reviewer_keeps_its_format(corpus):
    for question, answer in [(q, a) for q, a, _ in corpus.PAIRS] + list(corpus.REVIEWER_EXTRA):
        assert answer.startswith("VERDICT:"), f"reviewer answer without a verdict line: {question!r}"
        assert "\n- [" in answer, f"reviewer answer without severity bullets: {question!r}"


def test_the_tutor_keeps_its_format(corpus):
    for question, answer in [(q, b) for q, _, b in corpus.PAIRS] + list(corpus.TUTOR_EXTRA):
        assert "\n1. " in answer, f"tutor answer without numbered steps: {question!r}"
        assert "Check yourself:" in answer, f"tutor answer without a check-question: {question!r}"


def test_the_bard_answers_in_several_lines_of_verse(corpus):
    for question, answer in corpus.BARD:
        assert len(answer.splitlines()) >= 2, f"bard answer is not verse: {question!r}"


@pytest.fixture(scope="module")
def generator():
    """Import `training/data/build_datasets.py`, which imports `corpus` by path."""
    sys.path.insert(0, str(CORPUS_DIR))
    try:
        spec = importlib.util.spec_from_file_location("build_datasets", CORPUS_DIR / "build_datasets.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(CORPUS_DIR))


def test_the_software_personas_train_under_the_prompt_the_app_sends(generator):
    """If these drift, the adapters are conditioned on a prompt they never see at inference."""
    from agentchat import config

    assert generator.SYSTEM == config.SYSTEM_PROMPT


def test_the_bard_trains_under_the_prompt_the_app_sends_for_it(corpus):
    from agentchat import config

    assert corpus.BARD_SYSTEM == config.BARD_SYSTEM_PROMPT
