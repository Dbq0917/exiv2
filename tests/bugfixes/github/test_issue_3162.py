# -*- coding: utf-8 -*-

import pathlib
import shutil
import struct
import tempfile

import system_tests


def image_streams(filename):
    """Inspect the fixture's native image/alpha ranges independently of Exiv2."""
    data = pathlib.Path(filename).read_bytes()
    assert data[:4] == b"II\xbc\x01"
    offset = struct.unpack_from("<I", data, 4)[0]
    streams = []
    while offset:
        count = struct.unpack_from("<H", data, offset)[0]
        fields = {}
        for index in range(count):
            tag, kind, elements, value = struct.unpack_from(
                "<HHII", data, offset + 2 + 12 * index
            )
            if tag in (0xBCC0, 0xBCC1, 0xBCC2, 0xBCC3):
                assert kind == 4 and elements == 1
                fields[tag] = value
        for tag in (0xBCC0, 0xBCC2):
            if tag in fields:
                start = fields[tag]
                length = fields[tag + 1] or len(data) - start
                assert 0 < length <= len(data) - start
                streams.append(data[start:start + length])
        offset = struct.unpack_from("<I", data, offset + 2 + 12 * count)[0]
    return streams


def set_native_dimensions(filename, width, height):
    """Change only the target container geometry, as a differently sized source image would."""
    path = pathlib.Path(filename)
    data = bytearray(path.read_bytes())
    offset = struct.unpack_from("<I", data, 4)[0]
    count = struct.unpack_from("<H", data, offset)[0]
    for index in range(count):
        field = offset + 2 + 12 * index
        tag = struct.unpack_from("<H", data, field)[0]
        if tag == 0xBC80:
            struct.pack_into("<I", data, field + 8, width)
        if tag == 0xBC81:
            struct.pack_into("<I", data, field + 8, height)
    path.write_bytes(data)


def native_dimensions(filename):
    data = pathlib.Path(filename).read_bytes()
    offset = struct.unpack_from("<I", data, 4)[0]
    count = struct.unpack_from("<H", data, offset)[0]
    dimensions = {}
    for index in range(count):
        tag, _, _, value = struct.unpack_from("<HHII", data, offset + 2 + 12 * index)
        if tag in (0xBC80, 0xBC81):
            dimensions[tag] = value
    return dimensions[0xBC80], dimensions[0xBC81]


class JxrMetadataWriting(metaclass=system_tests.CaseMeta):
    """Growing and clearing real JXR metadata must preserve every compressed stream."""

    url = "https://github.com/Exiv2/exiv2/issues/3162"
    commands = []
    stdout = [""] * 3
    stderr = [""] * 3
    retval = [0] * 3
    stdin = [""] * 3

    def setUp(self):
        """Use a disposable fixture copy with an unrelated extension."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.filename = str(pathlib.Path(directory.name) / "image.data")
        source = self.expand_variables("$data_path/IMG_1913_8bit_prophoto_q50.jxr")
        shutil.copyfile(source, self.filename)
        self.original_streams = image_streams(source)
        executable = self.expand_variables("$exiv2")
        self.commands = [
            f'{executable} -M "set Exif.Image.Make JXR-MAKE-CANARY" "{self.filename}"',
            f'{executable} -M "set Exif.Image.Model {"G" * 2048}" "{self.filename}"',
            f'{executable} -da "{self.filename}"',
        ]

    def compare_stdout(self, index, command, got, expected):
        """Check source replacement and compressed bytes after every edit."""
        self.assertEqual(got, expected)
        self.assertEqual(self.original_streams, image_streams(self.filename))
        data = pathlib.Path(self.filename).read_bytes()
        self.assertEqual(index != 2, b"JXR-MAKE-CANARY" in data)


class JxrCrossResolutionCopy(metaclass=system_tests.CaseMeta):
    """Copying source metadata must not replace the target's dimensions or image stream."""

    url = "https://github.com/Exiv2/exiv2/issues/3162"
    commands = []
    stdout = [""] * 2
    stderr = [""] * 2
    retval = [0] * 2
    stdin = [""] * 2

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.source = str(pathlib.Path(directory.name) / "source.jxr")
        self.target = str(pathlib.Path(directory.name) / "target.jxr")
        fixture = self.expand_variables("$data_path/IMG_1913_8bit_prophoto_q50.jxr")
        shutil.copyfile(fixture, self.source)
        shutil.copyfile(fixture, self.target)
        set_native_dimensions(self.target, 1234, 567)
        self.target_streams = image_streams(self.target)
        exiv2 = self.expand_variables("$exiv2")
        metacopy = self.expand_variables("$metacopy")
        self.commands = [
            f'{exiv2} -M "set Exif.Image.Make CROSS-COPY-CANARY" "{self.source}"',
            f'{metacopy} -eix "{self.source}" "{self.target}"',
        ]

    def compare_stdout(self, index, command, got, expected):
        self.assertEqual(got, expected)
        if index == 1:
            self.assertEqual((1234, 567), native_dimensions(self.target))
            self.assertEqual(self.target_streams, image_streams(self.target))
            self.assertIn(b"CROSS-COPY-CANARY", pathlib.Path(self.target).read_bytes())
