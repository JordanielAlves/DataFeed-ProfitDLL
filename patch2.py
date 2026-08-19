import sys
with open('profit_bridge.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
in_cb = False
cb_indent = ''
for i, line in enumerate(lines):
    if line.strip().startswith('def _cb('):
        in_cb = True
        cb_indent = line[:len(line) - len(line.lstrip())]
        new_lines.append(line)
        new_lines.append(cb_indent + '    try:\n')
        continue
    
    if in_cb:
        if line.strip() == 'return _cb':
            in_cb = False
            new_lines.append(cb_indent + '    except Exception as e:\n')
            new_lines.append(cb_indent + '        import sys, traceback\n')
            new_lines.append(cb_indent + '        print(f\'\\n[FATAL] Exceção no callback: {e}\', file=sys.stderr)\n')
            new_lines.append(cb_indent + '        traceback.print_exc(file=sys.stderr)\n')
            new_lines.append(line)
        else:
            if line.strip() != '':
                new_lines.append('    ' + line)
            else:
                new_lines.append(line)
    else:
        new_lines.append(line)

with open('profit_bridge.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print('Callbacks protegidos.')
