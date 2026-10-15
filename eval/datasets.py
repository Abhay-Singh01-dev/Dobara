"""Evaluation data. ALL SYNTHETIC. Declared limitation: both sets were written in the same
AI-assisted session as the extractor, so results show the pipeline behaves as designed —
they are NOT evidence of real-world accuracy. The Build Round plan replaces this with a
held-out set written by people who have not seen the extractor (see SRS, AT-01)."""
import random

# gold: (fu_type, days_min, days_max, escalation_expected)

def templated(n=500, seed=7):
    rnd = random.Random(seed)
    pre = ["", "C/O fever x 3 days. ", "K/C/O DM, HTN. ", "Pain abdomen since 2 days. ",
           "Known case of MI. ", "BP 150/90. ", "Imp: viral fever. "]
    meds = ["", "Tab PCM 650 TDS x 5 days. ", "Tab Metformin 500 BD, continue for 1 month. ",
            "Syp cough 2 tsp TDS x 7d. "]
    units_en = [("days", 1), ("weeks", 7), ("months", 30)]
    units_hi = [("din", 1), ("hafte", 7), ("mahine", 30)]
    hi_nums = [("do", 2), ("teen", 3), ("char", 4), ("paanch", 5)]
    tests = ["CBC", "LFT", "HbA1c", "USG", "TSH", "KFT"]
    out = []
    for _ in range(n):
        k = rnd.randrange(16)
        n1 = rnd.choice([2, 3, 5, 7, 10, 14]); u, ud = rnd.choice(units_en)
        if ud == 30: n1 = rnd.choice([1, 2, 3, 6])
        if ud == 7: n1 = rnd.choice([1, 2, 3, 4, 6])
        t1, t2 = rnd.sample(tests, 2)
        if k == 0:   txt, g = f"Review after {n1} {u}.", ("DATED", n1*ud, n1*ud, None)
        elif k == 1: txt, g = f"R/V {n1} {'wks' if ud==7 else u} c reports.", ("DATED", n1*ud, n1*ud, None)
        elif k == 2:
            m, den = rnd.choice([(1, "52"), (2, "52"), (1, "12"), (3, "12"), (5, "7")])
            txt, g = f"f/u {m}/{den}", ("DATED", m*{"52":7,"12":30,"7":1}[den], m*{"52":7,"12":30,"7":1}[den], None)
        elif k == 3:
            (hw, hn), (hu, hd) = rnd.choice(hi_nums), rnd.choice(units_hi)
            txt, g = f"{hw} {hu} baad dikhayein.", ("DATED", hn*hd, hn*hd, None)
        elif k == 4:
            a = rnd.choice([3, 5, 7]); b = a + rnd.choice([2, 3])
            txt, g = f"{a}-{b} din baad aana, reports leke.", ("DATED", a, b, None)
        elif k == 5: txt, g = f"Review with {t1} report.", ("CONDITIONAL", None, None, None)
        elif k == 6: txt, g = "Review SOS.", ("SOS", None, None, None)
        elif k == 7: txt, g = "No follow-up needed.", ("NONE", None, None, None)
        elif k == 8: txt, g = f"R/V after {n1} {u} or SOS. Must come.", ("DATED", n1*ud, n1*ud, "E1")
        elif k == 9: txt, g = f"Follow up after {n1} {u} with {t1}, {t2}. Do not miss.", ("DATED", n1*ud, n1*ud, "E1")
        elif k == 10:
            dd = rnd.randint(10, 27)
            txt, g = f"Review on {dd}/11.", ("DATED", None, None, None)  # window computed vs visit date below
            g = ("ABS", dd, 11, None)
        elif k == 11: txt, g = "R/V 1 wk / 1 month", ("CONFLICT", None, None, None)
        elif k == 12: txt, g = f"Suture removal after {rnd.choice([7,10,12])} days.", None
        elif k == 13: txt, g = f"BP check after {n1} weeks, khali pet aana for FBS.", None
        elif k == 14: txt, g = "", ("UNCLEAR", None, None, None)
        else:        txt, g = f"Not urgent. Review after {n1} {u}.", ("DATED", n1*ud, n1*ud, None)
        if g is None:
            import re
            num = int(re.search(r"(\d+) (days|weeks)", txt).group(1))
            mult = 7 if "weeks" in txt else 1
            g = ("DATED", num*mult, num*mult, None)
        out.append((rnd.choice(pre) + rnd.choice(meds) + txt, g))
    return out


# Written by hand in a different style from the templates, BEFORE the first evaluation run.
# expected = gold reading a careful human would make.
ADVERSARIAL = [
    ("Pt to come back after a fortnight.", ("DATED", 14, 14, None)),
    ("rv in 10 days time", ("DATED", 10, 10, None)),
    ("Next visit 3 weeks.", ("DATED", 21, 21, None)),
    ("Review after 2 wks; repeat CBC after 1 wk.", ("DATED", 14, 14, None)),
    ("Continue same treatment for 1 month, then review.", ("DATED", 30, 30, None)),
    ("Tab Amlo 5mg OD x 1 month. RV 1 month.", ("DATED", 30, 30, None)),
    ("Review on 30/02.", ("CONFLICT", None, None, None)),
    ("Follow up 1/12 with lipid profile.", ("DATED", 30, 30, None)),
    ("F/U after 6 months in NCD clinic.", ("DATED", 180, 180, None)),
    ("Come back in 2 days if fever persists.", ("SOS", None, None, None)),
    ("Do not come before 1 week; review within 2 weeks.", ("DATED", 7, 14, None)),
    ("Review after reports.", ("CONDITIONAL", None, None, None)),
    ("Rv 2/52", ("DATED", 14, 14, None)),
    ("dikhane 15 din baad aayein", ("DATED", 15, 15, None)),
    ("agle hafte aana", ("DATED", 7, 7, None)),
    ("Review after 1 month. Must come with reports, urgent.", ("DATED", 30, 30, "E1")),
    ("Not urgent, routine review after 3 months.", ("DATED", 90, 90, None)),
    ("History of missed visits. Review in 2 weeks.", ("DATED", 14, 14, None)),
    ("Ca breast on chemo. Next cycle 21 days.", ("DATED", 21, 21, None)),
    ("Review after 2 weeks with USG abdomen.", ("DATED", 14, 14, None)),
    ("Stitches off on day 10.", ("DATED", 10, 10, None)),
    ("Review 1 wk", ("DATED", 7, 7, None)),
    ("Pt counselled. Discharged from OPD.", ("NONE", None, None, None)),
    ("R/V 3 days, if no improvement then admit.", ("DATED", 3, 3, None)),
    ("Tab Azithro 500 OD x 5 days. Review after 5 days.", ("DATED", 5, 5, None)),
    ("Follow-up 2 weeks. Follow-up 2 weeks.", ("DATED", 14, 14, None)),
    ("review 7 to 10 days", ("DATED", 7, 10, None)),
    ("Come after one week", ("DATED", 7, 7, None)),
    ("Imp: unstable angina. Review after 1 week.", ("DATED", 7, 7, None)),
    ("Sugar check after 15 days, khali pet.", ("DATED", 15, 15, None)),
]
