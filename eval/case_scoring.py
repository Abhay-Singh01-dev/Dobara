"""Supplementary case-selection model (NOT official judging weights; the case file gives none).
Criteria 1-6 mirror the six stated evaluation focus areas (case file p.2); 7-8 are our additions."""
criteria = ["Diagnosis depth","Evidence","Human-AI design","Build feasibility","Testability","Accountability","Differentiation","Significance"]
scores = {  # 1-5, justified in the decision record
 "1 AI for All":      [4,4,3,4,2,3,3,3],
 "2 Agriculture":     [4,4,3,2,3,3,3,5],
 "3 Healthcare":      [5,5,5,4,5,5,4,5],
 "4 Tourism":         [3,2,3,3,3,3,2,3],
 "5 Energy":          [4,2,2,3,4,4,3,4],
 "6 Sports":          [3,2,4,4,3,4,4,2],
 "7 Governance":      [4,3,5,4,4,5,3,4],
}
schemes = {
 "A Primary: official focus areas equal": [15,15,15,15,15,15,5,5],
 "B Originality-heavy":                   [10,10,10,10,10,10,25,15],
 "C Build-feasibility-heavy":             [10,10,15,25,20,10,5,5],
 "D Evidence-light (penalise data-rich)":  [20,0,20,15,15,15,10,5],
}
for name,w in schemes.items():
    assert sum(w)==100, name
    res = sorted(((sum(s*x for s,x in zip(sc,w))/5, c) for c,sc in scores.items()), reverse=True)
    print(f"\n{name}  weights={w}")
    for v,c in res: print(f"   {v:5.1f}  {c}")
    print(f"   margin #1 over #2: {res[0][0]-res[1][0]:.1f}")
# Robustness: how much would Healthcare's Differentiation need to drop for Governance to win under B?
