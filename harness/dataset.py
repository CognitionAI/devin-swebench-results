from typing import cast

from datasets import load_dataset, Dataset

from .types import SwebenchInstance


def get_dataset() -> list[SwebenchInstance]:
    dataset = cast(Dataset, load_dataset("princeton-nlp/SWE-bench", split="dev+test"))
    return [cast(SwebenchInstance, instance) for instance in dataset]
