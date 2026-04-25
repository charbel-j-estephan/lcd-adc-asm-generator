# LCD ASM Generator — PIC16F877A

A terminal-based tool that lets you **visually design a 16×2 LCD layout** and automatically generates complete, ready-to-flash **MPASM assembly code** for the PIC16F877A microcontroller.

No manual LCD assembly coding. No multiplication instructions. Just design, press `G`, and flash.

---

## Demo

```
┌────────────────┐
│A~00L           │   ← ADC value + static label
│ T~~L    HS     │   ← Numeric var + string var
└────────────────┘
```

Generates → `output.asm` with full LCD init, ADC read, BIN16BCD conversion, and display routines.

---

## Features

- **Visual LCD grid editor** — 16×2 cursor-based layout designer
- **ADC scaling via lookup table** — 10-bit ADC (0–1023) mapped to any range (0–8, 0–50, etc.) with pure compare-and-branch, no multiplication
- **Numeric variables** — 16-bit values displayed as decimal via double-dabble BIN16BCD
- **String variables** — multi-option strings (e.g. `EMPTY / HALF / FULL`) with PCL jump tables
- **Static characters** — type directly onto the LCD grid
- **Digit selection** — choose which BCD digits to display (U, T, H, Th) per variable
- **Full ASM output** — includes `CONFI`, `MAIN`, `READ_ADC`, `UPDATE_LCD`, `BIN16BCD`, `ADJBCD`, `SEND_DIGIT`, `COMMAND`, `CHAR`, `CONFILCD`, `DEL3`

---

## Hardware Target

| Item         | Detail                                        |
| ------------ | --------------------------------------------- |
| MCU          | PIC16F877A                                    |
| Oscillator   | 4 MHz crystal (HS mode)                       |
| LCD          | HD44780-compatible 16×2                       |
| LCD Data Bus | PORTD (RD0–RD7, 8-bit mode)                   |
| LCD RS       | RE2                                           |
| LCD EN       | RE0                                           |
| ADC Input    | AN0 (RA0), right-justified, Vdd/Vss reference |

---

## Requirements

```bash
# Run the tool
py -m pip install windows-curses

# Build standalone .exe (optional)
py -m pip install pyinstaller
py -m PyInstaller --onefile lcd_gen_v14.py
```

> **Run from Command Prompt**, not by double-clicking — curses requires a terminal.

---

## Usage

```bash
py lcd_gen_v14.py
```

| Key       | Action                                   |
| --------- | ---------------------------------------- |
| `A`       | Configure ADC (channel, name, max range) |
| `Z`       | Place ADC variable at cursor             |
| `N`       | Add numeric variable                     |
| `S`       | Add string variable                      |
| `G`       | Generate and save `output.asm`           |
| `Q`       | Quit                                     |
| `← → ↑ ↓` | Move cursor on LCD grid                  |
| Any char  | Place static character                   |

---

## ADC Scaling — No Multiplication

Instead of `ADC × max_range / 1023` (which requires a 16-bit multiply routine), the tool generates a **lookup table** of compare-and-branch instructions:

```asm
; ADC < 113 -> output 0
      MOVF ADC_H,W
      BTFSS STATUS,Z
      GOTO ADBIG_0
      MOVLW 0x71
      SUBWF ADC_L,W
      BTFSS STATUS,C
      GOTO SET_0
      GOTO ADBIG_0
SET_0
      MOVLW LOW(D'0')
      MOVWF ADCV_L
      ...
```

Thresholds are auto-calculated as `thr_i = i × (1024 / (max_range + 1))`.
Recommended for ranges ≤ 50. For larger ranges, use the shift approximation method.

---

## BIN16BCD — Double Dabble

Converts 16-bit binary to packed BCD using the standard double-dabble algorithm:

1. **Adjust** each BCD digit first (add 3 if nibble ≥ 5)
2. **Shift** the entire chain left: `REG1 → REG2 → BCD_0 → BCD_1 → BCD_2 → BCD_3`
3. Repeat 16 times

Key fix from v12→v14: adjust **before** shift, not after. The original version shifted twice per iteration, corrupting all BCD output.

---

## Register Map

| Register           | Address   | Purpose                  |
| ------------------ | --------- | ------------------------ |
| REG1–REG3          | 0x21–0x23 | Scratch                  |
| ADC_L / ADC_H      | 0x24–0x25 | Raw ADC result           |
| BCD_0–BCD_3        | 0x26–0x29 | BCD digits (U, T, H, Th) |
| ROFF / LCTR / TIDX | 0x2A–0x2C | String display helpers   |
| WTMP               | 0x2D      | ADJBCD temp register     |
| ADCV_L / ADCV_H    | 0x2E–0x2F | Scaled ADC output        |

---

## Bugs Fixed (v12 → v14)

### Bug 1 — Always displayed 000

`max_digits()` returned 2 for range 0–9, making the TUI offer `T` (tens) and `U` (units).
For values 0–8, the tens digit is always 0. **Fix:** `max_digits()` now returns 1 for `max_range ≤ 9`.

### Bug 2 — ADBIG comparison logic

The `BTFSS Z` + `BTFSC C` skip chain was wrong when `ADC_H < thr_h` — it fell through to the low-byte check instead of outputting the current value. **Fix:** explicit three-way branch with `GOTO SET_N / CHKL_N / ADBIG_N`.

### Bug 3 — BIN16BCD double-shift

The loop shifted `REG1→REG2` first, called `ADJBCD`, then shifted `BCD_0..3` again — two shifts per iteration. **Fix:** single unified `RLF` chain after `ADJBCD`, with `BCF STATUS,C` before the loop.

---

## Project Context

Built as part of **EEN 424 — Microprocessor System Design** at Notre Dame University, Lebanon.
Developed alongside a CNC PCB plotter project using PIC16F877A + ESP32 + Flask on Google Cloud Run.

---

## License

MIT — free to use, modify, and redistribute.
