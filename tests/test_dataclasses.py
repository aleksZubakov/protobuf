"""
`pure-protobuf` contributors © 2011-2022
"""

from dataclasses import dataclass
from typing import Any, ByteString, List, Optional, Tuple

from pytest import mark, raises

from pure_protobuf import types
# noinspection PyProtectedMember
from pure_protobuf.dataclasses_ import field, make_field, message


@mark.parametrize('number, name, type_, value, expected', [
    (1, 'a', types.int32, 150, b'\x08\x96\x01'),
    (1, 'a', List[types.int32], [1, 150, 2], b'\x0A\x04\x01\x96\x01\x02'),
    (1, 'a', List[bytes], [b'\x42', b'\x43'], b'\x0A\x01\x42' b'\x0A\x01\x43'),
    (1, 'a', Optional[bytes], None, b''),
    (1, 'a', ByteString, b'Testing', b'\x0A\x07Testing'),
    # TODO: repeated embedded message.
])
def test_make_field(number: int, name: str, type_: Any, value: Any, expected: bytes):
    _, field_ = make_field(number, name, type_)
    assert field_.name == name
    field_.validate(value)
    assert field_.dumps(value) == expected


@mark.parametrize('number, name, type_, value', [
    (1, 'a', types.int32, None),
    # TODO: invalid embedded message class.
])
def test_make_field_value_error(number: int, name: str, type_: Any, value: Any):
    _, field_ = make_field(number, name, type_)
    assert field_.name == name
    with raises(ValueError):
        field_.validate(value)


@mark.parametrize('type_', [
    Tuple[int, str],
])
def test_make_field_type_error(type_: Any):
    with raises(TypeError):
        make_field(1, 'a', type_)


def test_serialize_unpacked_repeated_field():
    @message
    @dataclass
    class Message:
        foo: List[types.uint32] = field(1, packed=False)

    assert Message(foo=[types.uint32(4), types.uint32(5)]).dumps() == b'\x08\x04\x08\x05'
