"""칠판에 적힌 방식(마찰 손실 측정)으로 계산하고 과정을 출력한다.

    A1V1 = A2V2 → V1 = V2,  z1 = z2,  K = 0
    ΔP = ρgΔh [Pa],  h_f = (p1 - p2)/ρg [m]
    Q [m³/s] = Q [L/h] / 3.6×10⁶,  V = Q / (π/4·d²),  Re = ρVd/μ
    h_f = f·(L/d)·V²/2g → f = h_f·(d/L)·2g/V²   (f를 Re에 대해 그린다)

d는 측정한 안지름(data.csv의 d_mm), L은 압력 탭 간격(L_mm)이다. L이 없으면 f = (f·L) / L로 출력한다.

사용법:
    python3 board.py data.csv
"""
import math
import sys

from calc import read_rows

RHO = 998.0  # kg/m³ (칠판)
MU = 0.001  # kg/(m·s) (칠판)
G = 9.81  # m/s² (칠판)


def board(row):
    d = row["d"] / 1000
    q_lph = row["Q_Lph"]
    q = q_lph / 3.6e6
    a = math.pi / 4 * d**2
    v = q / a
    re = RHO * v * d / MU
    dh = row["dh_mm"] / 1000
    dp = RHO * G * dh
    hf = dp / (RHO * G)
    vhead = v**2 / (2 * G)
    f_l = hf * d / vhead  # f × L [m]
    f = f_l / (row["L"] / 1000) if row["L"] else None
    return {"d": d, "Q_Lph": q_lph, "Q": q, "A": a, "V": v, "Re": re, "dh": dh, "dP": dp,
            "hf": hf, "vhead": vhead, "fL": f_l, "f": f}


def blasius(re):
    """매끈한 관의 난류 마찰계수(Blasius, Re < 10⁵). 무디 차트 비교용."""
    return 0.316 * re**-0.25


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    rows = [r for r in read_rows(sys.argv[1]) if r["dh_mm"] is not None]
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
        print(f"2. A = π/4 × d² = π/4 × {x['d']:.3f}² = {x['A']:.4e} m²")
        print(f"3. V = Q / A = {x['Q']:.4e} / {x['A']:.4e} = {x['V']:.4f} m/s")
        print(f"4. Re = ρVd/μ = {RHO:g} × {x['V']:.4f} × {x['d']:.3f} / {MU:g} = {x['Re']:,.0f}")
        print(f"5. ΔP = ρgΔh = {RHO:g} × {G:g} × {x['dh']:.3f} = {x['dP']:,.1f} Pa")
        print(f"6. h_f = ΔP / ρg = {x['dP']:,.1f} / ({RHO:g} × {G:g}) = {x['hf']:.3f} m")
        print(f"7. V²/2g = {x['V']:.4f}² / (2 × {G:g}) = {x['vhead']:.5f} m")
        line = f"8. f = h_f × (d/L) × 2g/V² = {x['hf']:.3f} × {x['d']:.3f} / ({x['vhead']:.5f} × L) = {x['fL']:.4g} / L[m]"
        if x["f"] is not None:
            line += f" = {x['fL']:.4g} / {r['L'] / 1000:g} = {x['f']:.4f}"
        print(line)
        print(f"   (비교: 매끈한 관 Blasius f = 0.316 Re^-0.25 = {blasius(x['Re']):.4f})\n")

    print("## 정리")
    print("| 요소 | d [m] | Q [m³/s] | V [m/s] | Re | ΔP [Pa] | h_f [m] | f | Blasius f |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r, x in results:
        f = f"{x['f']:.4f}" if x["f"] is not None else f"{x['fL']:.4g} / L"
        print(f"| {r['element']} | {x['d']:.3f} | {x['Q']:.4e} | {x['V']:.4f} | {x['Re']:,.0f} | "
              f"{x['dP']:,.1f} | {x['hf']:.3f} | {f} | {blasius(x['Re']):.4f} |")


if __name__ == "__main__":
    main()
