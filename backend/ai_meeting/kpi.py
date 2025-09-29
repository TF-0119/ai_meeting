# backend/ai_meeting/kpi.py
def jaccard(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb: return 0.0
    return len(sa & sb) / len(sa | sb)

def evaluate_diversity(texts: list[str]) -> float:
    if len(texts) < 2: return 1.0
    sims = [jaccard(texts[i], texts[i+1]) for i in range(len(texts)-1)]
    return 1.0 - sum(sims)/len(sims)
