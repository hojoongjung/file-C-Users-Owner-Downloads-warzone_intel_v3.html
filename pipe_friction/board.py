"""칠판에 적힌 방식(마찰 손실 측정)으로 계산하고 과정을 출력한다.

    A1V1 = A2V2 → V1 = V2,  z1 = z2,  K = 0
    ΔP = ρgΔh [Pa],  h_f = (p1 - p2)/ρg [m]
    Q [m³/s] = Q [L/h] / 3.6×10⁶,  V = Q / (π/4·d²),  Re = ρVd/μ
    h_f = f·(L/d)·V²/2g → f = h_f·(d/L)·2g/V²   (f를 Re에 대해 그린다)

d는 측정한 안지름(data.csv의 d_mm), L은 압력 탭 간격(L_mm, mm 단위)이다. L이 없으면 f = (f·L) / L[m]로 출력한다.
V1 = V2, K = 0은 두 탭이 같은 지름의 곧은 관에 있을 때만 맞으므로, 지름이 바뀌는 요소의 f는 겉보기 값이다.

사용법 (Windows는 python3 대신 py):
    python3 board.py data.csv
"""
import math
import sys

from calc import read_rows, utf8_output, warn

RHO = 998.0  # kg/m³ (칠판)
MU = 0.001  # kg/(m·s) (칠판)
G = 9.81  # m/s² (칠판)


def shown(x, spec):
    """출력에 보이는 자릿수로 반올림한 값. 다음 단계를 이 값으로 계산해야 손으로 검산한 값과 맞는다."""
    return float(format(x, spec))


def board(row):
    d = row["d"] / 1000
    q_lph = row["Q_Lph"]
    q = shown(q_lph / 3.6e6, ".4e")
    a = shown(math.pi / 4 * d**2, ".4e")
    v = shown(q / a, ".4f")
    re = RHO * v * d / MU
    dh = row["dh_mm"] / 1000
    dp = shown(RHO * G * dh, ".1f")
    hf = shown(dp / (RHO * G), ".4g")
    vhead = shown(v**2 / (2 * G), ".5f")
    f_l = shown(hf * d / vhead, ".4g")  # f × L [m]
    f = f_l / (row["L"] / 1000) if row["L"] else None
    return {"d": d, "Q_Lph": q_lph, "Q": q, "A": a, "V": v, "Re": re, "dh": dh, "dP": dp,
            "hf": hf, "vhead": vhead, "fL": f_l, "f": f}


def blasius(re):
    """매끈한 관의 난류 마찰계수(Blasius, Re < 10⁵). 무디 차트 비교용."""
    return 0.316 * re**-0.25


def main():
    utf8_output()
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    rows = read_rows(sys.argv[1])
    for r in rows:
        if r["dh_mm"] is None:
            warn(f"{r['element']} {r['Q_Lph']:g} L/h: 수두차가 없어 건너뜁니다.")
    rows = [r for r in rows if r["dh_mm"] is not None]
    missing = [r["element"] for r in rows if r["d"] is None]
    if missing:
        sys.exit(f"d_mm(안지름)이 없는 측정: {', '.join(missing)}")
    if not rows:
        print("수두차가 있는 측정값이 아직 없습니다.")
        return

    print(f"상수(칠판): ρ = {RHO:g} kg/m³, μ = {MU:g} kg/(m·s), g = {G:g} m/s²\n")
    results = []
    for r in rows:
        x = board(r)
        results.append((r, x))
        print(f"## {r['element']} (d = {r['d']:g} mm)")
        print(f"1. Q = {x['Q_Lph']:g} L/h ÷ 3.6×10⁶ = {x['Q']:.4e} m³/s")
        print(f"2. A = π/4 × d² = π/4 × {x['d']:g}² = {x['A']:.4e} m²")
        print(f"3. V = Q / A = {x['Q']:.4e} / {x['A']:.4e} = {x['V']:.4f} m/s")
        print(f"4. Re = ρVd/μ = {RHO:g} × {x['V']:.4f} × {x['d']:g} / {MU:g} = {x['Re']:,.0f}")
        print(f"5. ΔP = ρgΔh = {RHO:g} × {G:g} × {x['dh']:g} = {x['dP']:,.1f} Pa")
        print(f"6. h_f = ΔP / ρg = {x['dP']:,.1f} / ({RHO:g} × {G:g}) = {x['hf']:.4g} m")
        print(f"7. V²/2g = {x['V']:.4f}² / (2 × {G:g}) = {x['vhead']:.5f} m")
        line = (f"8. f = h_f × (d/L) × 2g/V² = {x['hf']:.4g} × {x['d']:g} / ({x['vhead']:.5f} × L)"
                f" = {x['fL']:.4g} / L[m]")
        if x["f"] is not None:
            line += f" = {x['fL']:.4g} / {r['L'] / 1000:g} = {x['f']:.4f}"
        print(line)
        if r["element"] == "직관":
            print(f"   (비교: 매끈한 관 Blasius f = 0.316 Re^-0.25 = {blasius(x['Re']):.4f})\n")
        else:
            print("   (지름이 바뀌는 요소라 V1 = V2가 아니다. 이 f는 겉보기 값이다.)\n")

    print("## 정리")
    print("| 요소 | d [m] | Q [m³/s] | V [m/s] | Re | ΔP [Pa] | h_f [m] | f | Blasius f (직관 비교용) |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r, x in results:
        f = f"{x['f']:.4f}" if x["f"] is not None else f"{x['fL']:.4g} / L[m]"
        bl = f"{blasius(x['Re']):.4f}" if r["element"] == "직관" else "—"
        print(f"| {r['element']} | {x['d']:g} | {x['Q']:.4e} | {x['V']:.4f} | {x['Re']:,.0f} | "
              f"{x['dP']:,.1f} | {x['hf']:.4g} | {f} | {bl} |")


if __name__ == "__main__":
    main()
