"""관로마찰 실험 계산: 측정값 CSV → 유속, Re, 손실계수 K, 마찰계수 f, 유량계수 C.

사용법:
    python3 calc.py data.csv --temp 20
    python3 calc.py example_slide.csv --nu 1.00e-6   # 슬라이드 예시 검산

CSV 열: element, Q_Lph, h1_mm, h2_mm, dh_mm, note
    - dh_mm = h1_mm - h2_mm (상류 탭 - 하류 탭). h1, h2를 따로 적으면 dh_mm은 비워도 된다.
    - element: 급확대관, 급축소관, 오리피스관, 벤투리관, 직관
    - '#'으로 시작하는 줄은 주석.
"""
import argparse
import csv
import math
import sys

G = 9.81  # m/s²

# 장치 치수 [mm] (슬라이드 '파이프 직경' 표). 교재 표 5-1은 다른 장치 값이라 쓰지 않는다.
GEOMETRY = {
    "급확대관": {"D1": 25.0, "D2": 40.0},
    "급축소관": {"D1": 40.0, "D2": 25.0},
    "오리피스관": {"D1": 25.0, "D2": 20.0},
    "벤투리관": {"D1": 32.0, "D2": 20.0},
    # 직관: 안지름 D와 압력 탭 간격 L [mm]을 재서 넣는다.
    "직관": {"D": None, "L": None},
}

# 직관 내벽 절대 조도 [mm]. PVC 같은 플라스틱 관은 약 0.0015mm(매끈한 관에 가깝다).
ROUGHNESS_MM = 0.0015

# 물의 온도 [°C], 밀도 [kg/m³], 점성계수 [Pa·s] (Çengel 유체역학 표 A-3)
WATER = [
    (0, 999.8, 1.792e-3),
    (5, 999.9, 1.519e-3),
    (10, 999.7, 1.307e-3),
    (15, 999.1, 1.138e-3),
    (20, 998.0, 1.002e-3),
    (25, 997.0, 0.891e-3),
    (30, 996.0, 0.798e-3),
    (35, 994.0, 0.720e-3),
    (40, 992.1, 0.653e-3),
]


def water_props(temp_c):
    """온도에서 (밀도, 점성계수)를 선형 보간한다."""
    if not WATER[0][0] <= temp_c <= WATER[-1][0]:
        sys.exit(f"물 온도 {temp_c}°C는 표 범위(0~40°C) 밖입니다.")
    for (t0, r0, m0), (t1, r1, m1) in zip(WATER, WATER[1:]):
        if t0 <= temp_c <= t1:
            w = (temp_c - t0) / (t1 - t0)
            return r0 + w * (r1 - r0), m0 + w * (m1 - m0)


def area(d_mm):
    return math.pi / 4 * (d_mm / 1000) ** 2


def normalize(name):
    key = name.replace(" ", "")
    if key not in GEOMETRY and key + "관" in GEOMETRY:
        key += "관"
    return key


def expansion(q, dh, nu):
    """급확대관. 기준 속도는 작은 관(상류) 속도."""
    d, D = GEOMETRY["급확대관"]["D1"], GEOMETRY["급확대관"]["D2"]
    v1, v2 = q / area(d), q / area(D)
    return {
        "V": v1,
        "Re": v1 * d / 1000 / nu,
        "K_slide": dh * 2 * G / v1**2,
        "K_corr": (dh + (v1**2 - v2**2) / (2 * G)) * 2 * G / v1**2,
    }


def contraction(q, dh, nu):
    """급축소관. 기준 속도는 작은 관(하류) 속도."""
    D, d = GEOMETRY["급축소관"]["D1"], GEOMETRY["급축소관"]["D2"]
    v1, v2 = q / area(D), q / area(d)
    return {
        "V": v2,
        "Re": v2 * d / 1000 / nu,
        "K_slide": dh * 2 * G / v2**2,
        "K_corr": (dh + (v1**2 - v2**2) / (2 * G)) * 2 * G / v2**2,
    }


def flowmeter(element, q, dh, nu):
    """차압식 유량계. 식 (5.7) Q_이론 = A2/√(1-(A2/A1)²)·√(2gΔh), C = Q/Q_이론."""
    D1, D2 = GEOMETRY[element]["D1"], GEOMETRY[element]["D2"]
    a1, a2 = area(D1), area(D2)
    v1, v2 = q / a1, q / a2
    q_th = a2 / math.sqrt(1 - (a2 / a1) ** 2) * math.sqrt(2 * G * dh) if dh > 0 else float("nan")
    return {
        "V": v2,
        "Re": v2 * D2 / 1000 / nu,
        "Re_pipe": v1 * D1 / 1000 / nu,
        "Q_th": q_th,
        "C": q / q_th,
    }


def venturi_c_theory(beta):
    """슬라이드 식 C ≈ 0.9858 - 0.196β^4.5."""
    return 0.9858 - 0.196 * beta**4.5


def orifice_c_theory(beta, re_pipe):
    """그림 5-7(D·D/2 탭) 곡선을 만든 ISO 5167 근사식(White, Fluid Mechanics). Re는 관 기준."""
    f_beta = 0.5959 + 0.0312 * beta**2.1 - 0.184 * beta**8
    return (
        f_beta
        + 91.71 * beta**2.5 * re_pipe**-0.75
        + 0.09 * beta**4 / (1 - beta**4) * 0.4333
        - 0.0337 * beta**3 * 0.47
    )


def colebrook(re, rel_rough):
    """무디 차트 난류 영역(Colebrook 식). Haaland 값에서 시작해 반복."""
    f = (-1.8 * math.log10((rel_rough / 3.7) ** 1.11 + 6.9 / re)) ** -2
    for _ in range(50):
        f = (-2 * math.log10(rel_rough / 3.7 + 2.51 / (re * math.sqrt(f)))) ** -2
    return f


def straight(q, dh, nu):
    """직관. f = Δh·(D/L)·2g/V² (식 5.3)."""
    D, L = GEOMETRY["직관"]["D"], GEOMETRY["직관"]["L"]
    if D is None or L is None:
        sys.exit("직관 안지름 D와 탭 간격 L을 calc.py의 GEOMETRY['직관']에 먼저 넣어 주세요.")
    v = q / area(D)
    re = v * D / 1000 / nu
    f_moody = 64 / re if re < 2300 else colebrook(re, ROUGHNESS_MM / D)
    return {"V": v, "Re": re, "f": dh * (D / L) * 2 * G / v**2, "f_moody": f_moody}


def read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        lines = [line for line in f if line.strip() and not line.lstrip().startswith("#")]
    rows = []
    for i, r in enumerate(csv.DictReader(lines), start=1):
        element = normalize(r["element"] or "")
        if element not in GEOMETRY:
            sys.exit(f"{i}번째 측정: 알 수 없는 element '{r['element']}'")
        if (r.get("dh_mm") or "").strip():
            dh_mm = float(r["dh_mm"])
        elif (r.get("h1_mm") or "").strip() and (r.get("h2_mm") or "").strip():
            dh_mm = float(r["h1_mm"]) - float(r["h2_mm"])
        else:
            sys.exit(f"{i}번째 측정({element}): dh_mm 또는 h1_mm, h2_mm이 필요합니다.")
        rows.append({
            "element": element,
            "Q_Lph": float(r["Q_Lph"]),
            "dh_mm": dh_mm,
            "note": (r.get("note") or "").strip(),
        })
    return rows


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + " --- |" * len(headers)]
    out += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="측정값 CSV")
    ap.add_argument("--temp", type=float, default=20.0, help="물 온도 [°C] (기본 20)")
    ap.add_argument("--nu", type=float, help="동점성계수 [m²/s]를 직접 지정(슬라이드는 1.00e-6)")
    args = ap.parse_args()

    rows = read_rows(args.csv)
    if not rows:
        print("측정값이 아직 없습니다.")
        return

    rho, mu = water_props(args.temp)
    nu = args.nu if args.nu else mu / rho
    print(f"물 {args.temp:g}°C: ρ = {rho:.1f} kg/m³, μ = {mu:.3e} Pa·s, ν = {nu:.3e} m²/s\n")

    for element in GEOMETRY:
        group = [r for r in rows if r["element"] == element]
        if not group:
            continue
        out = []
        for r in group:
            q = r["Q_Lph"] / 1000 / 3600
            dh = r["dh_mm"] / 1000
            base = [f"{r['Q_Lph']:g}", f"{q:.3e}", f"{r['dh_mm']:g}"]
            if element == "급확대관":
                res = expansion(q, dh, nu)
                out.append(base + [f"{res['V']:.3f}", f"{res['Re']:.0f}",
                                   f"{res['K_slide']:.3f}", f"{res['K_corr']:.3f}", r["note"]])
            elif element == "급축소관":
                res = contraction(q, dh, nu)
                out.append(base + [f"{res['V']:.3f}", f"{res['Re']:.0f}",
                                   f"{res['K_slide']:.3f}", f"{res['K_corr']:.3f}", r["note"]])
            elif element == "벤투리관":
                res = flowmeter(element, q, dh, nu)
                beta = GEOMETRY[element]["D2"] / GEOMETRY[element]["D1"]
                out.append(base + [f"{res['V']:.3f}", f"{res['Re']:.0f}", f"{res['Q_th']:.3e}",
                                   f"{res['C']:.3f}", f"{venturi_c_theory(beta):.3f}", r["note"]])
            elif element == "오리피스관":
                res = flowmeter(element, q, dh, nu)
                beta = GEOMETRY[element]["D2"] / GEOMETRY[element]["D1"]
                out.append(base + [f"{res['V']:.3f}", f"{res['Re']:.0f}", f"{res['Re_pipe']:.0f}",
                                   f"{res['Q_th']:.3e}", f"{res['C']:.3f}",
                                   f"{orifice_c_theory(beta, res['Re_pipe']):.3f}", r["note"]])
            elif element == "직관":
                res = straight(q, dh, nu)
                out.append(base + [f"{res['V']:.3f}", f"{res['Re']:.0f}",
                                   f"{res['f']:.4f}", f"{res['f_moody']:.4f}", r["note"]])

        head = ["Q [L/h]", "Q [m³/s]", "Δh [mm]"]
        g = GEOMETRY[element]
        if element in ("급확대관", "급축소관"):
            d, D = min(g["D1"], g["D2"]), max(g["D1"], g["D2"])
            k_th = (1 - (d / D) ** 2) ** 2 if element == "급확대관" else 0.42 * (1 - (d / D) ** 2)
            print(f"## {element} ({g['D1']:g} → {g['D2']:g} mm), 이론 K = {k_th:.3f}")
            head += ["V 작은 관 [m/s]", "Re", "K 슬라이드식", "K 속도수두 보정", "비고"]
        elif element == "벤투리관":
            print(f"## 벤투리관 (D1 {g['D1']:g}, D2 {g['D2']:g} mm, β = {g['D2'] / g['D1']:.3f})")
            head += ["V 목 [m/s]", "Re 목", "Q이론 [m³/s]", "C 실험", "C 이론", "비고"]
        elif element == "오리피스관":
            print(f"## 오리피스관 (D1 {g['D1']:g}, D2 {g['D2']:g} mm, β = {g['D2'] / g['D1']:.3f})")
            head += ["V 목 [m/s]", "Re 목", "Re 관", "Q이론 [m³/s]", "C 실험", "C 이론", "비고"]
        elif element == "직관":
            print(f"## 직관 (D {g['D']:g} mm, L {g['L']:g} mm, ε {ROUGHNESS_MM} mm)")
            head += ["V [m/s]", "Re", "f 실험", "f 무디", "비고"]
        print(table(head, out))
        print()


if __name__ == "__main__":
    main()
