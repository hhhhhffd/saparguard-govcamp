from __future__ import annotations
from collections import Counter
from typing import Iterable

def classification_metrics(expected: list[str], predicted: list[str]) -> dict[str, object]:
    labels=sorted(set(expected)|set(predicted)); matrix={label:{other:0 for other in labels} for label in labels}
    for actual, guess in zip(expected,predicted,strict=True): matrix[actual][guess]+=1
    per_class={}
    for label in labels:
        tp=matrix[label][label]; fp=sum(matrix[other][label] for other in labels if other != label); fn=sum(matrix[label][other] for other in labels if other != label)
        precision=tp/(tp+fp) if tp+fp else 0; recall=tp/(tp+fn) if tp+fn else 0
        per_class[label]={"precision":precision,"recall":recall,"f1":2*precision*recall/(precision+recall) if precision+recall else 0,"support":sum(matrix[label].values())}
    return {"accuracy":sum(a==b for a,b in zip(expected,predicted,strict=True))/len(expected) if expected else None,"macro_precision":sum(v["precision"] for v in per_class.values())/len(per_class) if per_class else None,"macro_recall":sum(v["recall"] for v in per_class.values())/len(per_class) if per_class else None,"macro_f1":sum(v["f1"] for v in per_class.values())/len(per_class) if per_class else None,"per_class":per_class,"confusion_matrix":matrix}

def entity_metrics(expected: list[set[str]], predicted: list[set[str]]) -> dict[str, object]:
    tp=sum(len(a&b) for a,b in zip(expected,predicted,strict=True)); fp=sum(len(b-a) for a,b in zip(expected,predicted,strict=True)); fn=sum(len(a-b) for a,b in zip(expected,predicted,strict=True)); precision=tp/(tp+fp) if tp+fp else 0; recall=tp/(tp+fn) if tp+fn else 0
    return {"precision":precision,"recall":recall,"f1":2*precision*recall/(precision+recall) if precision+recall else 0,"exact_message_accuracy":sum(a==b for a,b in zip(expected,predicted,strict=True))/len(expected) if expected else None}
