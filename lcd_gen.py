import curses

RESERVED = {
    "STATUS",
    "PORTB",
    "PORTC",
    "PORTD",
    "PORTE",
    "PORTA",
    "TRISB",
    "TRISC",
    "TRISD",
    "TRISE",
    "TRISA",
    "PCL",
    "PCLATH",
    "INTCON",
    "ADCON0",
    "ADCON1",
    "REG1",
    "REG2",
    "REG3",
    "ADC_L",
    "ADC_H",
    "BCD_0",
    "BCD_1",
    "BCD_2",
    "BCD_3",
    "ROFF",
    "LCTR",
    "TIDX",
    "MAIN",
    "CONFI",
    "UPDATE_LCD",
    "WTMP",
}

_ADCON1 = [
    (0x0E, "AN0"),
    (0x0D, "AN0-1"),
    (0x09, "AN0-3"),
    (0x02, "AN0-4"),
    (0x00, "AN0-7"),
]

DIGIT_LABELS = ["U", "T", "H", "Th"]
DIGIT_BCDREG = ["BCD_0", "BCD_1", "BCD_2", "BCD_3"]


# ======================================================================
# Lookup table generator  (replaces MUL16)
# ======================================================================
def generate_lookup_asm(max_range, adc_var):
    """
    Generate READ_ADC using compare-and-branch lookup table.
    ADC is 10-bit right justified (ADRESH:ADRESL, 0-1023).
    Output mapped to 0..max_range stored in {adc_var}_H:{adc_var}_L.
    Strategy:
      - Compare ADRESH first (high byte, 0-3 for 10-bit)
      - Then compare ADRESL (low byte) for fine resolution
      - Each bucket sets the output value directly
    """
    N = max_range + 1  # number of output values (0..max_range)
    ADC_MAX = 1023
    step = (ADC_MAX + 1) / N  # ADC counts per output step

    # Build threshold list: ADC value where output increments
    thresholds = []
    for i in range(1, N):
        thresholds.append(int(i * step))

    o = ""
    o += "; -------------------------------------------------------\n"
    o += f"; READ_ADC: Lookup table scaling 0-1023 -> 0-{max_range}\n"
    o += "; No multiplication. Pure compare-and-branch.\n"
    o += "; ADFM=1 (right justified), reads ADRESH:ADRESL\n"
    o += "; -------------------------------------------------------\n"
    o += "ADC_INIT\n"
    o += "      MOVLW 0x41\n"  # Fosc/8, channel 0, ADC ON (ADCON0)
    o += "      MOVWF ADCON0\n"
    o += "      RETURN\n\n"

    o += "READ_ADC\n"
    o += "      BSF ADCON0,2\n"  # Start conversion
    o += "ADWT  BTFSC ADCON0,2\n"  # Wait for GO/DONE to clear
    o += "      GOTO ADWT\n"
    o += "      MOVF ADRESH,W\n"
    o += "      MOVWF ADC_H\n"
    o += "      BSF STATUS,RP0\n"  # Bank 1 to read ADRESL
    o += "      MOVF ADRESL,W\n"
    o += "      BCF STATUS,RP0\n"
    o += "      MOVWF ADC_L\n"
    o += "      GOTO ADLUT\n"  # Jump into lookup table
    o += "      RETURN\n\n"

    # ---- Lookup table ----
    o += "; --- ADC Lookup Table ---\n"
    o += "ADLUT\n"

    for i, thr in enumerate(thresholds):
        out_val = i  # output value for ADC < thr
        thr_h = thr >> 8  # high byte of threshold (0-3)
        thr_l = thr & 0xFF  # low byte of threshold

        o += f"      ; --- ADC < {thr} -> output {out_val} ---\n"

        chk = f"CHKL_{i}"
        big = f"ADBIG_{i}"
        setn = f"SET_{i}"

        if thr_h == 0:
            # ADC_H must be 0; if > 0 definitely >= thr
            o += f"      MOVF ADC_H,W\n"
            o += f"      BTFSS STATUS,Z\n"  # skip if ADC_H == 0
            o += f"      GOTO {big}\n"  # ADC_H > 0 -> too big
            # ADC_H == 0, compare low byte
            o += f"      MOVLW 0x{thr_l:02X}\n"
            o += f"      SUBWF ADC_L,W\n"  # W = ADC_L - thr_l
            o += f"      BTFSS STATUS,C\n"  # skip if ADC_L >= thr_l (C=1)
            o += f"      GOTO {setn}\n"  # C=0 -> ADC_L < thr_l -> output
            o += f"      GOTO {big}\n"
        else:
            # Three-way compare of high byte
            o += f"      MOVLW 0x{thr_h:02X}\n"
            o += f"      SUBWF ADC_H,W\n"  # W = ADC_H - thr_h
            o += f"      BTFSC STATUS,Z\n"  # skip if ADC_H != thr_h
            o += f"      GOTO {chk}\n"  # equal -> compare low byte
            o += f"      BTFSS STATUS,C\n"  # skip if ADC_H > thr_h (C=1)
            o += f"      GOTO {setn}\n"  # C=0 -> ADC_H < thr_h -> output
            o += f"      GOTO {big}\n"  # ADC_H > thr_h -> next bucket
            o += f"{chk}\n"
            o += f"      MOVLW 0x{thr_l:02X}\n"
            o += f"      SUBWF ADC_L,W\n"  # W = ADC_L - thr_l
            o += f"      BTFSS STATUS,C\n"  # skip if ADC_L >= thr_l
            o += f"      GOTO {setn}\n"
            o += f"      GOTO {big}\n"

        # Output this value
        o += f"{setn}\n"
        o += f"      MOVLW LOW(D'{out_val}')\n"
        o += f"      MOVWF {adc_var}_L\n"
        o += f"      MOVLW HIGH(D'{out_val}')\n"
        o += f"      MOVWF {adc_var}_H\n"
        o += f"      RETURN\n"
        o += f"{big}\n"

    # Last bucket: output = max_range
    o += f"      ; ADC >= {thresholds[-1] if thresholds else 0} -> output {max_range}\n"
    o += f"      MOVLW LOW(D'{max_range}')\n"
    o += f"      MOVWF {adc_var}_L\n"
    o += f"      MOVLW HIGH(D'{max_range}')\n"
    o += f"      MOVWF {adc_var}_H\n"
    o += f"      RETURN\n\n"

    return o, len(thresholds) + 1  # code, number of buckets


# ======================================================================
# Warning check
# ======================================================================
MAX_LOOKUP_RANGE = 50  # above this, lookup table gets too large for practical use


class ADCConfig:
    def __init__(self):
        self.enabled = False
        self.channel = 0
        self.num_sensors = 0
        self.var_name = "ADCV"
        self.max_range = 8

    def adcon1_val(self):
        # Right justified (ADFM=1) + selected channels
        return _ADCON1[self.num_sensors][0] | 0x80

    def max_digits(self):
        if self.max_range > 999:
            return 4
        if self.max_range > 99:
            return 3
        if self.max_range > 9:
            return 2
        return 1  # 0-9: units only

    def available_digits(self):
        return DIGIT_LABELS[: self.max_digits()][::-1]

    def lookup_too_large(self):
        return self.max_range > MAX_LOOKUP_RANGE


class LCDSystem:
    def __init__(self):
        self.grid = [[" " for _ in range(16)] for _ in range(2)]
        self.vars = {}
        self.lcd_data = [[None for _ in range(16)] for _ in range(2)]
        self.adc = ADCConfig()

    def add_static(self, r, c, char):
        self.lcd_data[r][c] = {"type": "static", "char": char}
        self.grid[r][c] = char

    def add_var(self, r, c, name, vtype, width, extras):
        name = name.upper().strip()
        if not name or name in RESERVED:
            return False
        for row in range(2):
            for col in range(16):
                cell = self.lcd_data[row][col]
                if (
                    cell
                    and cell.get("name") == name
                    and cell.get("digits") == extras.get("digits")
                ):
                    self.lcd_data[row][col] = None
                    self.grid[row][col] = " "
        self.vars[name] = {"type": vtype, "width": width, **extras}
        for i in range(width):
            if c + i < 16:
                self.lcd_data[r][c + i] = {
                    "name": name,
                    "type": vtype,
                    "isStart": (i == 0),
                    "width": width,
                    "digits": extras.get("digits"),
                }
                self.grid[r][c + i] = name[0] if i == 0 else "~"
        return True

    # ------------------------------------------------------------------
    # ASM generation
    # ------------------------------------------------------------------
    def generate_asm(self):
        o = "; AUTO-GENERATED ASM - V13 LOOKUP TABLE ADC\n"
        o += '#INCLUDE "P16F877A.INC"\n'
        o += "__CONFIG _HS_OSC & _WDT_OFF & _LVP_OFF\n\n"

        # --- Registers (MUL_L/M/H removed - no longer needed) ---
        regs = [
            "REG1",
            "REG2",
            "REG3",
            "ADC_L",
            "ADC_H",
            "BCD_0",
            "BCD_1",
            "BCD_2",
            "BCD_3",
            "ROFF",
            "LCTR",
            "TIDX",
            "WTMP",
        ]
        for i, reg in enumerate(regs):
            o += f"{reg} EQU 0x{0x21+i:02X}\n"

        addr = 0x21 + len(regs)
        if self.adc.enabled:
            o += f"{self.adc.var_name}_L EQU 0x{addr:02X}\n"
            o += f"{self.adc.var_name}_H EQU 0x{addr+1:02X}\n"
            addr += 2

        for name in sorted(self.vars):
            if self.adc.enabled and name == self.adc.var_name:
                continue
            o += f"{name}_L EQU 0x{addr:02X}\n"
            o += f"{name}_H EQU 0x{addr+1:02X}\n"
            addr += 2

        # --- Init ---
        o += "\n      ORG 0x00\nCONFI\n"
        o += "      BSF STATUS,RP0\n"
        o += "      MOVLW 0xFF\n      MOVWF TRISA\n"
        o += "      CLRF TRISD\n      CLRF TRISE\n"
        if self.adc.enabled:
            o += f"      MOVLW 0x{self.adc.adcon1_val():02X}\n"
            o += "      MOVWF ADCON1\n"
        o += "      BCF STATUS,RP0\n"
        o += "      CALL CONFILCD\n"
        if self.adc.enabled:
            o += "      CALL ADC_INIT\n"
        o += "\nMAIN\n"
        if self.adc.enabled:
            o += "      CALL READ_ADC\n"
        o += "      CALL UPDATE_LCD\n      CALL DEL3\n      GOTO MAIN\n\n"

        # --- UPDATE_LCD ---
        o += "UPDATE_LCD\n"
        used_disp = []
        seen_disp = set()

        for row in range(2):
            line_addr = 0x80 if row == 0 else 0xC0
            o += f"      MOVLW 0x{line_addr:02X}\n      CALL COMMAND\n"
            for col in range(16):
                d = self.lcd_data[row][col]
                if not d:
                    o += "      MOVLW 0x20\n      CALL CHAR\n"
                elif d.get("isStart"):
                    name = d["name"]
                    digits = d.get("digits")
                    label = self._disp_label(name, digits)
                    o += f"      MOVF {name}_L,W\n      MOVWF REG1\n"
                    o += f"      MOVF {name}_H,W\n      MOVWF REG2\n"
                    o += f"      CALL {label}\n"
                    key = (name, digits)
                    if key not in seen_disp:
                        seen_disp.add(key)
                        used_disp.append((name, digits))
                elif d["type"] == "static":
                    o += f"      MOVLW 0x{ord(d['char']):02X}\n      CALL CHAR\n"
        o += "      RETURN\n\n"

        # --- DISP_* routines ---
        for name, digits in used_disp:
            label = self._disp_label(name, digits)
            v = self.vars.get(name)
            o += f"{label}\n"

            is_adc = self.adc.enabled and name == self.adc.var_name
            is_num = v and v["type"] == "num"

            if is_adc or is_num:
                o += "      CALL BIN16BCD\n"
                if is_adc and digits:
                    letter_to_bcd = {
                        "Th": "BCD_3",
                        "H": "BCD_2",
                        "T": "BCD_1",
                        "U": "BCD_0",
                    }
                    ordered = self._parse_digits_msb_first(digits)
                    for dl in ordered:
                        bcd = letter_to_bcd[dl]
                        o += f"      MOVF {bcd},W\n      CALL SEND_DIGIT\n"
                else:
                    if (is_adc and self.adc.max_range > 999) or (
                        is_num and v["width"] > 3
                    ):
                        o += "      MOVF BCD_3,W\n      CALL SEND_DIGIT\n"
                    o += "      MOVF BCD_2,W\n      CALL SEND_DIGIT\n"
                    o += "      MOVF BCD_1,W\n      CALL SEND_DIGIT\n"
                    o += "      MOVF BCD_0,W\n      CALL SEND_DIGIT\n"

            elif v and v["type"] == "str":
                w = v["width"]
                o += f"      MOVWF TIDX\n      CALL PT_{name}\n      MOVWF ROFF\n"
                o += f"      MOVLW D'{w}'\n      MOVWF LCTR\n"
                o += f"LP_{name}\n      MOVF ROFF,W\n      CALL TB_{name}\n"
                o += f"      CALL CHAR\n      INCF ROFF,F\n"
                o += f"      DECFSZ LCTR,F\n      GOTO LP_{name}\n"

            o += "      RETURN\n\n"

            if v and v["type"] == "str":
                o += f"PT_{name}\n      MOVF TIDX,W\n      ADDWF PCL,F\n"
                for i in range(len(v["options"])):
                    o += f"      RETLW D'{i*w}'\n"
                o += f"TB_{name}\n      ADDWF PCL,F\n"
                for opt in v["options"]:
                    for char in opt.ljust(w)[:w]:
                        o += f"      RETLW 0x{ord(char):02X}\n"

        # --- ADC: LOOKUP TABLE (replaces MUL16 entirely) ---
        if self.adc.enabled:
            lut_asm, buckets = generate_lookup_asm(
                self.adc.max_range, self.adc.var_name
            )
            o += f"; Lookup table: {buckets} buckets for range 0-{self.adc.max_range}\n"
            o += lut_asm

        # --- BIN16BCD (fixed double-dabble: adjust BEFORE shift) ---
        o += "BIN16BCD\n"
        o += "      CLRF BCD_0\n      CLRF BCD_1\n      CLRF BCD_2\n      CLRF BCD_3\n"
        o += "      BCF STATUS,C\n"  # clear carry before first shift
        o += "      MOVLW D'16'\n      MOVWF REG3\n"
        o += "B16LP\n"
        o += "      MOVLW BCD_0\n      MOVWF FSR\n      CALL ADJBCD\n"
        o += "      MOVLW BCD_1\n      MOVWF FSR\n      CALL ADJBCD\n"
        o += "      MOVLW BCD_2\n      MOVWF FSR\n      CALL ADJBCD\n"
        o += "      MOVLW BCD_3\n      MOVWF FSR\n      CALL ADJBCD\n"
        o += "      RLF REG1,F\n      RLF REG2,F\n"
        o += "      RLF BCD_0,F\n      RLF BCD_1,F\n      RLF BCD_2,F\n      RLF BCD_3,F\n"
        o += "      DECFSZ REG3,F\n      GOTO B16LP\n      RETURN\n\n"

        o += "ADJBCD MOVF INDF,W\n"
        o += "      ADDLW 0x03\n      MOVWF WTMP\n"
        o += "      BTFSC WTMP,3\n      MOVWF INDF\n"
        o += "      MOVF INDF,W\n"
        o += "      ADDLW 0x30\n      MOVWF WTMP\n"
        o += "      BTFSC WTMP,7\n      MOVWF INDF\n"
        o += "      RETURN\n\n"

        o += "SEND_DIGIT\n      ANDLW 0x0F\n      ADDLW 0x30\n      CALL CHAR\n      RETURN\n\n"
        o += "COMMAND\n      BCF PORTE,2\n      MOVWF PORTD\n      BSF PORTE,0\n      NOP\n      BCF PORTE,0\n      CALL DEL3\n      RETURN\n\n"
        o += "CHAR\n      BSF PORTE,2\n      MOVWF PORTD\n      BSF PORTE,0\n      NOP\n      BCF PORTE,0\n      CALL DEL3\n      RETURN\n\n"
        o += "CONFILCD\n      CALL DEL3\n      MOVLW 0x38\n      CALL COMMAND\n      MOVLW 0x0C\n      CALL COMMAND\n      MOVLW 0x01\n      CALL COMMAND\n      RETURN\n\n"
        o += "DEL3\n      MOVLW D'100'\n      MOVWF REG2\n"
        o += "DL1    MOVLW D'255'\n      MOVWF REG1\n"
        o += "DL2    DECFSZ REG1,F\n      GOTO DL2\n      DECFSZ REG2,F\n      GOTO DL1\n      RETURN\n"
        o += "      END"
        return o

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _disp_label(self, name, digits):
        if digits:
            safe = digits.replace("Th", "K")
            return f"DISP_{name}_{safe}"
        return f"DISP_{name}"

    def _parse_digits_msb_first(self, digits_str):
        all_tokens = ["Th", "H", "T", "U"]
        remaining = digits_str
        requested = []
        for tok in all_tokens:
            if tok in remaining:
                requested.append(tok)
                remaining = remaining.replace(tok, "", 1)
        return requested


# ======================================================================
# ADC digit selection wizard
# ======================================================================
def adc_digit_wiz(stdscr, adc):
    available = adc.available_digits()
    selected = set(available)

    while True:
        stdscr.erase()
        stdscr.addstr(
            1, 2, "SELECT DIGITS  (1-4=toggle  ENTER=confirm)", curses.color_pair(3)
        )
        stdscr.addstr(
            2,
            2,
            f"Variable: {adc.var_name}   Max: {adc.max_range}",
            curses.color_pair(2),
        )

        for i, d in enumerate(available):
            mark = "[X]" if d in selected else "[ ]"
            stdscr.addstr(4 + i, 4, f"{i+1}. {mark} {d}")

        stdscr.addstr(
            4 + len(available) + 1, 2, f"Width: {len(selected)}", curses.color_pair(1)
        )

        k = stdscr.getch()
        if k in (ord("\n"), ord("g")):
            if not selected:
                selected = set(available)
            return "".join(d for d in available if d in selected)
        for i, d in enumerate(available):
            if k == ord(str(i + 1)):
                if d in selected:
                    selected.discard(d)
                else:
                    selected.add(d)


# ======================================================================
# ADC setup wizard
# ======================================================================
def adc_wiz(stdscr, adc):
    p = 0
    while True:
        stdscr.erase()
        too_large = adc.lookup_too_large()
        stdscr.addstr(
            1, 2, f"ADC SETUP [P{p+1}/3]  LEFT/RIGHT=page  G=done", curses.color_pair(3)
        )

        if p == 0:
            stdscr.addstr(3, 2, f"Channel: AN{adc.channel}  (UP/DOWN)")
        elif p == 1:
            stdscr.addstr(3, 2, f"Name: {adc.var_name}  (R to rename)")
        elif p == 2:
            stdscr.addstr(3, 2, f"Max Range: {adc.max_range}  (M to change)")
            stdscr.addstr(
                4, 2, f"Buckets: {adc.max_range + 1}   Digits: {adc.max_digits()}"
            )
            stdscr.addstr(5, 2, f"Method: LOOKUP TABLE (no multiplication)")
            if too_large:
                stdscr.addstr(
                    7,
                    2,
                    f"!! Range {adc.max_range} > {MAX_LOOKUP_RANGE}: table may be too large!",
                    curses.color_pair(3),
                )
            else:
                stdscr.addstr(7, 2, "OK - fits in program memory", curses.color_pair(1))

        k = stdscr.getch()
        if k == curses.KEY_RIGHT:
            p = min(2, p + 1)
        elif k == curses.KEY_LEFT:
            p = max(0, p - 1)
        elif k == ord("g"):
            adc.enabled = True
            return
        elif p == 0:
            if k == curses.KEY_UP:
                adc.channel = (adc.channel - 1) % 8
            elif k == curses.KEY_DOWN:
                adc.channel = (adc.channel + 1) % 8
        elif p == 1 and k == ord("r"):
            curses.echo()
            stdscr.addstr(5, 4, "Name: ")
            adc.var_name = stdscr.getstr().decode().upper().strip()
            curses.noecho()
        elif p == 2 and k == ord("m"):
            curses.echo()
            stdscr.addstr(8, 4, f"Max (1-{MAX_LOOKUP_RANGE} recommended): ")
            try:
                adc.max_range = int(stdscr.getstr().decode())
            except Exception:
                pass
            curses.noecho()


# ======================================================================
# Main TUI
# ======================================================================
def main(stdscr):
    curses.init_pair(1, curses.COLOR_GREEN, 0)
    curses.init_pair(2, curses.COLOR_CYAN, 0)
    curses.init_pair(3, curses.COLOR_YELLOW, 0)
    lcd = LCDSystem()
    r, c = 0, 0
    msg = ""

    while True:
        stdscr.erase()
        stdscr.addstr(
            1,
            2,
            "LCD GEN v13 - [A]ADC [N]NUM [S]STR [Z]PLACE ADC [G]GEN [Q]QUIT",
            curses.color_pair(3),
        )

        # ADC status bar
        if lcd.adc.enabled:
            warn = " !! LARGE" if lcd.adc.lookup_too_large() else ""
            stdscr.addstr(
                2,
                2,
                f"ADC: {lcd.adc.var_name} | range 0-{lcd.adc.max_range} | {lcd.adc.max_range+1} buckets{warn}",
                curses.color_pair(2 if not lcd.adc.lookup_too_large() else 3),
            )

        stdscr.addstr(3, 4, "┌" + "─" * 16 + "┐")
        for i in range(2):
            stdscr.addstr(4 + i, 4, "│")
            for j in range(16):
                d = lcd.lcd_data[i][j]
                col = curses.color_pair(2 if d and d["type"] != "static" else 1)
                stdscr.addstr(4 + i, 5 + j, lcd.grid[i][j], col)
            stdscr.addstr(4 + i, 21, "│")
        stdscr.addstr(6, 4, "└" + "─" * 16 + "┘")

        if msg:
            stdscr.addstr(8, 2, msg, curses.color_pair(2))
        stdscr.move(4 + r, 5 + c)

        k = stdscr.getch()
        msg = ""

        if k == ord("q"):
            break
        elif k == curses.KEY_UP:
            r = 0
        elif k == curses.KEY_DOWN:
            r = 1
        elif k == curses.KEY_LEFT:
            c = max(0, c - 1)
        elif k == curses.KEY_RIGHT:
            c = min(15, c + 1)
        elif k == ord("a"):
            adc_wiz(stdscr, lcd.adc)
            msg = f"ADC: {lcd.adc.var_name} range=0-{lcd.adc.max_range}"
        elif k == ord("z"):
            if not lcd.adc.enabled:
                msg = "Configure ADC first with [A]!"
            else:
                digits = adc_digit_wiz(stdscr, lcd.adc)
                width = len([d for d in lcd.adc.available_digits() if d in digits])
                if width == 0:
                    width = lcd.adc.max_digits()
                lcd.add_var(r, c, lcd.adc.var_name, "num", width, {"digits": digits})
                msg = f"ADC placed: {digits} ({width} digit(s))"
        elif k == ord("n"):
            curses.echo()
            stdscr.addstr(8, 2, "Name: ")
            name = stdscr.getstr().decode().upper().strip()
            stdscr.addstr(9, 2, "Width (2-5): ")
            try:
                w = int(stdscr.getstr().decode())
            except Exception:
                w = 3
            curses.noecho()
            if lcd.add_var(r, c, name, "num", w, {}):
                msg = f"Num {name} added."
            else:
                msg = f"Name '{name}' reserved/invalid."
        elif k == ord("s"):
            curses.echo()
            stdscr.addstr(8, 2, "Name: ")
            name = stdscr.getstr().decode().upper().strip()
            stdscr.addstr(9, 2, "Options (CSV): ")
            raw = stdscr.getstr().decode().split(",")
            curses.noecho()
            opts = [o.strip() for o in raw]
            if lcd.add_var(
                r, c, name, "str", len(max(opts, key=len)), {"options": opts}
            ):
                msg = f"Str {name} added."
            else:
                msg = f"Name '{name}' reserved/invalid."
        elif k == ord("g"):
            with open("output.asm", "w") as f:
                f.write(lcd.generate_asm())
            msg = "Saved output.asm!"
        elif 32 <= k <= 126:
            lcd.add_static(r, c, chr(k))
            c = min(15, c + 1)


curses.wrapper(main)
