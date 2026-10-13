"""관로마찰 실험 계산: 측정값 CSV → 유속, Re, 손실계수 K, 마찰계수 f, 유량계수 C.

사용법 (Windows는 python3 대신 py):
    python3 calc.py data.csv --temp 20
    python3 calc.py example_slide.csv --nu 1.00e-6   # 슬라이드 예시 검산

CSV 열: element, Q_Lph, Q_Lpm, D1_mm, D2_mm, d_mm, L_mm, h1_mm, h2_mm, dh_mm, note
    - element: 급확대관, 급축소관, 오리피스관, 벤투리관, 직관
    - 유량은 Q_Lph(L/h) 또는 Q_Lpm(L/min, 유량계의 10~80 눈금) 중 하나를 적는다.
    - D1_mm, D2_mm(상류, 하류 안지름)을 적으면 GEOMETRY 기본값 대신 쓴다. 손글씨 표의 외경/내경과는 다르다.
    - d_mm(측정한 안지름), L_mm(탭 간격)은 칠판 방식 계산(board.py)에서 쓴다. 직관은 이 두 칸에만 적는다.
    - dh_mm = h1_mm - h2_mm (상류 탭 - 하류 탭). h1, h2를 따로 적으면 dh_mm은 비워도 된다.
      수두차가 아직 없으면 비워 둔다(유속과 Re만 계산).
    - '#'으로 시작하는 줄은 주석. 엑셀에서 저장한 CSV(UTF-8 또는 한글 cp949)도 읽는다.
"""
import argparse
import csv
import math
import sys

G = 9.81  # m/s²

# 장치 지름 [mm] (슬라이드 '파이프 직경' 표, 안지름인지 표시는 없다). 교재 표 5-1은 다른 장치 값이라 쓰지 않는다.
GEOMETRY = {
    "급확대관": {"D1": 25.0, "D2": 40.0},
    "급축소관": {"D1": 40.0, "D2": 25.0},
    "오리피스관": {"D1": 25.0, "D2": 20.0},
    "벤투리관": {"D1": 32.0, "D2": 20.0},
    # 직관: 행마다 d_mm(안지름)과 L_mm(압력 탭 간격)을 적는다. 안에서는 D1 = d, D2 = L로 쓴다.
    "직관": {"D1": None, "D2": None},
}

# 유량계 눈금 범위. 10~80 눈금은 L/min, 옆 눈금은 L/h(60배, 600~5000)다.
FLOWMETER_LPH = (600, 5000)

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


def expansion(q, dh, nu, d, D):
    """급확대관 d → D. 기준 속도는 작은 관(상류) 속도."""
    v1, v2 = q / area(d), q / area(D)
    res = {"V": v1, "Re": v1 * d / 1000 / nu, "K_th": (1 - (d / D) ** 2) ** 2}
    res["hL_th"] = res["K_th"] * v1**2 / (2 * G)
    if dh is not None:
        res["hL_corr"] = dh + (v1**2 - v2**2) / (2 * G)
        res["K_slide"] = dh * 2 * G / v1**2
        res["K_corr"] = res["hL_corr"] * 2 * G / v1**2
    return res


def contraction(q, dh, nu, D, d):
    """급축소관 D → d. 기준 속도는 작은 관(하류) 속도."""
    v1, v2 = q / area(D), q / area(d)
    res = {"V": v2, "Re": v2 * d / 1000 / nu, "K_th": 0.42 * (1 - (d / D) ** 2)}
    res["hL_th"] = res["K_th"] * v2**2 / (2 * G)
    if dh is not None:
        res["hL_corr"] = dh + (v1**2 - v2**2) / (2 * G)
        res["K_slide"] = dh * 2 * G / v2**2
        res["K_corr"] = res["hL_corr"] * 2 * G / v2**2
    return res


def flowmeter(q, dh, nu, D1, D2):
    """차압식 유량계. 식 (5.7) Q_이론 = A2/√(1-(A2/A1)²)·√(2gΔh), C = Q/Q_이론."""
    a1, a2 = area(D1), area(D2)
    v1, v2 = q / a1, q / a2
    res = {"V": v2, "Re": v2 * D2 / 1000 / nu, "Re_pipe": v1 * D1 / 1000 / nu, "beta": D2 / D1}
    if dh is not None:
        res["Q_th"] = a2 / math.sqrt(1 - (a2 / a1) ** 2) * math.sqrt(2 * G * dh) if dh > 0 else float("nan")
        res["C"] = q / res["Q_th"]
        res["hL"] = dh - (v2**2 - v1**2) / (2 * G)
    return res


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


def straight(q, dh, nu, D, L):
    """직관. f = Δh·(D/L)·2g/V² (식 5.3)."""
    v = q / area(D)
    re = v * D / 1000 / nu
    res = {"V": v, "Re": re, "f_moody": 64 / re if re < 2300 else colebrook(re, ROUGHNESS_MM / D)}
    if dh is not None and L:
        res["f"] = dh * (D / L) * 2 * G / v**2
    return res


def cell(r, key):
    value = r.get(key)
    return value.strip() if isinstance(value, str) else ""


def warn(message):
    print(f"주의: {message}", file=sys.stderr)


def utf8_output():
    """한글 Windows에서 결과를 파일로 돌려도(>) 깨지거나 멈추지 않게 한다."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def read_text(path):
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            return f.read()
    except UnicodeDecodeError:
        pass
    try:
        # 한글 엑셀에서 'CSV(쉼표로 분리)'로 저장하면 cp949가 된다.
        with open(path, encoding="cp949", newline="") as f:
            return f.read()
    except UnicodeDecodeError:
        sys.exit(f"{path}: CSV 텍스트로 읽을 수 없습니다. 엑셀에서 'CSV UTF-8' 또는 'CSV(쉼표로 분리)'로 저장하세요(.xlsx는 못 읽습니다).")


def read_rows(path):
    # (파일 줄 번호, 줄). 주석과 빈 줄, 엑셀이 남긴 쉼표만 있는 줄은 뺀다.
    numbered = [(n, line) for n, line in enumerate(read_text(path).splitlines(keepends=True), start=1)
                if line.replace(",", "").strip() and not line.lstrip().startswith("#")]
    reader = csv.DictReader(line for _, line in numbered)
    if not reader.fieldnames or "element" not in [h.strip() for h in reader.fieldnames]:
        sys.exit("CSV 머리글(첫 줄)에 element 열이 없습니다. data.csv의 머리글을 그대로 쓰세요.")
    rows = []
    for r in reader:
        i = numbered[reader.line_num - 1][0]
        r = {(k.strip() if isinstance(k, str) else k): v for k, v in r.items()}
        element = normalize(cell(r, "element"))
        if element not in GEOMETRY:
            sys.exit(f"{i}번째 줄: 알 수 없는 element '{cell(r, 'element')}' (가능: {', '.join(GEOMETRY)})")
        tag = f"{i}번째 줄({element})"
        if any(isinstance(v, str) and v.strip() for v in r.get(None) or []):
            warn(f"{tag}: 칸이 머리글보다 많습니다. note에 쉼표가 있으면 따옴표로 감싸세요.")

        def num(key):
            text = cell(r, key)
            if text in ("", "-"):
                return None
            try:
                value = float(text)
            except ValueError:
                value = math.nan
            if not math.isfinite(value):
                sys.exit(f"{tag} {key}: 숫자가 아닙니다 ({text!r}).")
            return value

        q_lph, q_lpm = num("Q_Lph"), num("Q_Lpm")
        if q_lph is None and q_lpm is None:
            sys.exit(f"{tag}: Q_Lph 또는 Q_Lpm이 필요합니다.")
        if q_lph is not None and q_lpm is not None and abs(q_lph - 60 * q_lpm) > 0.5:
            warn(f"{tag}: Q_Lph({q_lph:g})와 Q_Lpm({q_lpm:g} → {60 * q_lpm:g} L/h)이 다릅니다. Q_Lph를 씁니다.")
        q = q_lph if q_lph is not None else 60 * q_lpm
        if q <= 0:
            sys.exit(f"{tag}: 유량이 0 이하입니다.")
        lo, hi = FLOWMETER_LPH
        if not lo <= q <= hi:
            hint = ""
            if q_lph is not None and q < lo:
                hint = " 10~80 눈금 값(V값)이면 Q_Lpm 칸에 적으세요."
            elif q_lph is None and q > hi:
                hint = " L/h 눈금 값이면 Q_Lph 칸에 적으세요."
            warn(f"{tag}: 유량 {q:g} L/h는 유량계 눈금({lo}~{hi} L/h) 밖입니다.{hint}")

        dh_mm, h1, h2 = num("dh_mm"), num("h1_mm"), num("h2_mm")
        if dh_mm is None and h1 is not None and h2 is not None:
            dh_mm = h1 - h2
        elif dh_mm is None and (h1 is None) != (h2 is None):
            warn(f"{tag}: h1_mm, h2_mm 중 하나만 있어 수두차를 계산하지 않습니다.")
        elif dh_mm is not None and h1 is not None and h2 is not None and abs(dh_mm - (h1 - h2)) > 0.5:
            warn(f"{tag}: dh_mm({dh_mm:g})과 h1_mm − h2_mm({h1 - h2:g})이 다릅니다. dh_mm을 씁니다.")

        d, L = num("d_mm"), num("L_mm")
        for key, value in (("d_mm", d), ("L_mm", L), ("D1_mm", num("D1_mm")), ("D2_mm", num("D2_mm"))):
            if value is not None and value <= 0:
                sys.exit(f"{tag} {key}: 0보다 커야 합니다.")
        if element == "직관":
            if num("D1_mm") is not None or num("D2_mm") is not None:
                sys.exit(f"{tag}: 직관은 D1_mm/D2_mm 대신 d_mm(안지름)과 L_mm(탭 간격)에 적어 주세요.")
            if d is None:
                sys.exit(f"{tag}: 안지름 d_mm을 적어 주세요.")
            D1, D2 = d, L
        else:
            D1 = num("D1_mm")
            D2 = num("D2_mm")
            D1 = GEOMETRY[element]["D1"] if D1 is None else D1
            D2 = GEOMETRY[element]["D2"] if D2 is None else D2
            expanding = element == "급확대관"
            if not (D1 < D2 if expanding else D1 > D2):
                need = "D1_mm < D2_mm" if expanding else "D1_mm > D2_mm"
                sys.exit(f"{tag}: {need}이어야 합니다. D1_mm, D2_mm은 상류·하류 안지름이지 손글씨의 외경/내경이 아닙니다.")
        rows.append({
            "element": element,
            "Q_Lph": q,
            "dh_mm": dh_mm,
            "D1": D1,
            "D2": D2,
            "d": d,
            "L": L,
            "note": cell(r, "note"),
        })
    return rows


def fmt(value, spec):
    return "—" if value is None else format(value, spec)


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + " --- |" * len(headers)]
    out += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(out)


HEADERS = {
    "급확대관": ["V 작은 관 [m/s]", "Re", "h_L 보정 [m]", "h_L 이론 [m]", "K 슬라이드식", "K 속도수두 보정", "K 이론"],
    "급축소관": ["V 작은 관 [m/s]", "Re", "h_L 보정 [m]", "h_L 이론 [m]", "K 슬라이드식", "K 속도수두 보정", "K 이론"],
    # Δh − (V2² − V1²)/2g = (1 − C²)Δh: 입구~목 사이 값이고, 확산부까지 포함한 영구 손실은 아니다.
    "벤투리관": ["β", "V 목 [m/s]", "Re 목", "Re 관", "Δh − (V2²−V1²)/2g [m]", "Q이론 [m³/s]", "C 실험", "C 이론"],
    "오리피스관": ["β", "V 목 [m/s]", "Re 목", "Re 관", "Δh − (V2²−V1²)/2g [m]", "Q이론 [m³/s]", "C 실험", "C 이론"],
    "직관": ["V [m/s]", "Re", "f 실험", "f 무디"],
}


def compute(r, nu):
    """한 측정의 결과 열(문자열 목록)을 만든다."""
    element, D1, D2 = r["element"], r["D1"], r["D2"]
    q = r["Q_Lph"] / 1000 / 3600
    dh = None if r["dh_mm"] is None else r["dh_mm"] / 1000
    if element == "급확대관":
        res = expansion(q, dh, nu, D1, D2)
        return [fmt(res["V"], ".3f"), fmt(res["Re"], ".0f"), fmt(res.get("hL_corr"), ".4f"),
                fmt(res["hL_th"], ".4f"), fmt(res.get("K_slide"), ".3f"),
                fmt(res.get("K_corr"), ".3f"), fmt(res["K_th"], ".3f")]
    if element == "급축소관":
        res = contraction(q, dh, nu, D1, D2)
        return [fmt(res["V"], ".3f"), fmt(res["Re"], ".0f"), fmt(res.get("hL_corr"), ".4f"),
                fmt(res["hL_th"], ".4f"), fmt(res.get("K_slide"), ".3f"),
                fmt(res.get("K_corr"), ".3f"), fmt(res["K_th"], ".3f")]
    if element == "벤투리관":
        res = flowmeter(q, dh, nu, D1, D2)
        return [fmt(res["beta"], ".3f"), fmt(res["V"], ".3f"), fmt(res["Re"], ".0f"), fmt(res["Re_pipe"], ".0f"),
                fmt(res.get("hL"), ".4f"), fmt(res.get("Q_th"), ".3e"), fmt(res.get("C"), ".3f"), fmt(venturi_c_theory(res["beta"]), ".3f")]
    if element == "오리피스관":
        res = flowmeter(q, dh, nu, D1, D2)
        return [fmt(res["beta"], ".3f"), fmt(res["V"], ".3f"), fmt(res["Re"], ".0f"), fmt(res["Re_pipe"], ".0f"),
                fmt(res.get("hL"), ".4f"), fmt(res.get("Q_th"), ".3e"), fmt(res.get("C"), ".3f"),
                fmt(orifice_c_theory(res["beta"], res["Re_pipe"]), ".3f")]
    res = straight(q, dh, nu, D1, D2)
    return [fmt(res["V"], ".3f"), fmt(res["Re"], ".0f"), fmt(res.get("f"), ".4f"), fmt(res["f_moody"], ".4f")]


def main():
    utf8_output()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="측정값 CSV")
    ap.add_argument("--temp", type=float, default=20.0, help="물 온도 [°C] (기본 20)")
    ap.add_argument("--nu", type=float, help="동점성계수 [m²/s]를 직접 지정(슬라이드는 1.00e-6)")
    args = ap.parse_args()

    rows = read_rows(args.csv)
    if not rows:
        print("측정값이 아직 없습니다.")
        return

    if args.nu:
        nu = args.nu
        print(f"ν = {nu:.3e} m²/s (직접 지정)\n")
    else:
        rho, mu = water_props(args.temp)
        nu = mu / rho
        print(f"물 {args.temp:g}°C: ρ = {rho:.1f} kg/m³, μ = {mu:.3e} Pa·s, ν = {nu:.3e} m²/s\n")

    for element in GEOMETRY:
        group = [r for r in rows if r["element"] == element]
        if not group:
            continue
        dim = "D [mm], L [mm]" if element == "직관" else "D1 → D2 [mm]"
        head = ["Q [L/h]", "Q [m³/s]", dim, "Δh [mm]"] + HEADERS[element] + ["비고"]
        out = []
        for r in group:
            q = r["Q_Lph"] / 1000 / 3600
            dims = f"{r['D1']:g}, {fmt(r['D2'], 'g')}" if element == "직관" else f"{r['D1']:g} → {r['D2']:g}"
            out.append([f"{r['Q_Lph']:g}", f"{q:.3e}", dims, fmt(r["dh_mm"], "g")] + compute(r, nu) + [r["note"]])
        print(f"## {element}")
        print(table(head, out))
        print()


if __name__ == "__main__":
    main()
