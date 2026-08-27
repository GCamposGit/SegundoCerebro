"""Optional converters that run *before* a parser, from `reader.py` only.

Parsers still receive bytes and never touch the filesystem. LibreOffice lives
here because both C7.a (recalc) and R1.1 (legacy convert) need the same binary.
"""
