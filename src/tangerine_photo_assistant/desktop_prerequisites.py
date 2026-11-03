"""Read-only prerequisite checks before pywebview can fall back to legacy IE."""


def registry_value(hive, path, name):
    import winreg

    try:
        with winreg.OpenKey(getattr(winreg, hive), path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def missing_prerequisites(read=registry_value):
    missing = []
    release = read('HKEY_LOCAL_MACHINE', r'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release')
    if not isinstance(release, int) or release < 394802:
        missing.append('.NET Framework 4.6.2 或更新版本')
    runtime_id = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    installed = False
    for hive, prefix in [('HKEY_CURRENT_USER', 'SOFTWARE'),
                         ('HKEY_LOCAL_MACHINE', r'SOFTWARE\WOW6432Node')]:
        value = read(hive, prefix + '\\Microsoft\\EdgeUpdate\\Clients\\' + runtime_id, 'pv')
        try:
            installed |= int(str(value).split('.')[0]) >= 86
        except ValueError:
            pass
    if not installed:
        missing.append('Microsoft Edge WebView2 Runtime')
    return missing
