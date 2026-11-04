"""Read the actual PE shell icon resources without opening an executable or Explorer."""
import argparse
import hashlib
import struct
from pathlib import Path
from xml.etree import ElementTree

import pefile


def resources(pe, kind):
    directory = next(e for e in pe.DIRECTORY_ENTRY_RESOURCE.entries if e.id == kind)
    result = {}
    for entry in directory.directory.entries:
        data = entry.directory.entries[0].data.struct
        result[entry.id] = pe.get_data(data.OffsetToData, data.Size)
    return result


def verify_icons(bundle, setup, *programs):
    master = (Path(__file__).resolve().parents[1] / 'assets/tangerine-photo-assistant.ico').read_bytes()
    assert (bundle / '_internal/assets/tangerine-photo-assistant.ico').read_bytes() == master
    count = struct.unpack_from('<H', master, 4)[0]
    expected = {}
    for w, h, _, _, _, _, size, offset in struct.iter_unpack('<BBBBHHII', master[6:6+16*count]):
        expected[w or 256, h or 256] = master[offset:offset+size]
    for path in (setup, *programs):
        with pefile.PE(str(path), fast_load=True) as pe:
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
            group = next(iter(resources(pe, 14).values()))
            images = resources(pe, 3)
            actual = {(w or 256, h or 256): images[index][:size]
                      for w, h, _, _, _, _, size, index in struct.iter_unpack('<BBBBHHIH', group[6:])}
            assert actual == expected, f'{path.name}: embedded shell icon differs from product ICO'
            if path == setup:
                xml = ElementTree.fromstring(next(iter(resources(pe, 24).values())).rstrip(b'\0'))
                level = xml.find('.//{*}requestedExecutionLevel')
                assert level is not None and level.get('level') == 'asInvoker'
    print('Verified embedded icon sizes', sorted(w for w, _ in expected),
          'source SHA-256', hashlib.sha256(master).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', type=Path)
    parser.add_argument('setup', type=Path)
    args = parser.parse_args()
    verify_icons(args.bundle, args.setup, args.bundle / 'TangerinePhotoAssistant.exe')
