"""XTest additions for actual shifted ASCII and keypad keys in isolated checks."""
from x11 import X as BaseX


class X(BaseX):
    def key(self, name):
        # XKeysymToKeycode chooses a physical key, not its shift level.
        # Explicitly press Shift so applications really receive case/symbols.
        shifted = dict(zip('~!@#$%^&*()_+{}|:"<>?', '`1234567890-=[]\\;\',./'))
        if len(name) == 1 and (name.isupper() or name in shifted):
            base = name.lower() if name.isupper() else shifted[name]
            self.press(0xFFE1, True)
            try:
                super().key(base)
            finally:
                self.press(0xFFE1, False)
        elif name == 'KP_Decimal':
            self.press(0xFFAE, True)
            self.press(0xFFAE, False)
        elif name in {'Home','End','Left','Right','Delete','Num_Lock'} or name.startswith('KP_'):
            values = dict(Home=0xFF50, End=0xFF57, Left=0xFF51, Right=0xFF53,
                          Delete=0xFFFF, Num_Lock=0xFF7F)
            keysym = 0xFFB0 + int(name[3:]) if name.startswith('KP_') else values[name]
            self.press(keysym, True)
            self.press(keysym, False)
        else:
            super().key(name)
