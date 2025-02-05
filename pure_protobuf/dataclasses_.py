#!/usr/bin/env python3

"""
Python 3.6+ type hinting interface.
"""

from abc import ABC
from collections import abc
from enum import IntEnum
from io import BytesIO
from typing import Any, ByteString, ClassVar, Dict, Iterable, List, Tuple, Type, TypeVar, Union, cast, get_type_hints

from pure_protobuf import serializers, types
from pure_protobuf.enums import WireType
from pure_protobuf.fields import Field, NonRepeatedField, PackedRepeatedField, UnpackedRepeatedField
from pure_protobuf.io_ import IO
from pure_protobuf.serializers import IntEnumSerializer, MessageSerializer, PackingSerializer, Serializer
from pure_protobuf.types import NoneType

try:
    import dataclasses
except ImportError:
    raise ImportError('dataclasses interface requires dataclasses support')


T = TypeVar('T')
TMessage = TypeVar('TMessage', bound='Message')


@dataclasses.dataclass
class Message(ABC):
    """
    Virtual base class for a message type.
    See also: https://docs.python.org/3/library/abc.html#abc.ABCMeta.register
    """

    __protobuf_fields__: Dict[int, Field]
    serializer: ClassVar[Serializer]
    type_url: ClassVar[str]

    def validate(self):
        self.serializer.validate(self)

    def dump(self, io: IO):
        """
        Serializes a message into a file-like object.
        """
        self.validate()
        self.serializer.dump(self, io)

    def dumps(self) -> bytes:
        """
        Serializes a message into a byte string.
        """
        with BytesIO() as io:
            self.dump(io)
            return io.getvalue()

    def merge_from(self: TMessage, other: TMessage):
        """
        Merge another message into the current one, as if with the ``Message::MergeFrom`` method.
        """
        for field_ in self.__protobuf_fields__.values():
            setattr(self, field_.name, field_.merge(
                getattr(self, field_.name),
                getattr(other, field_.name),
            ))


class OneOf:
    """
    Defines an oneof field.
    See also: https://developers.google.com/protocol-buffers/docs/proto3#oneof
    """
    def __init__(self, *fields: Field):
        self.fields = fields
        # TODO: implement automatic clearing.

    def __get__(self, message_: Message, owner: Type = None) -> Any:
        """
        Retrieve the currently set value (if any).
        """
        for field_ in self.fields:
            value = getattr(message_, field_.name)
            if value is not None:
                return value
        return None


def load(cls: Type[TMessage], io: IO) -> TMessage:
    """
    Deserializes a message from a file-like object.
    """
    return cls.serializer.load(io)


def loads(cls: Type[TMessage], bytes_: bytes) -> TMessage:
    """
    Deserializes a message from a byte string.
    """
    with BytesIO(bytes_) as io:
        return load(cls, io)


def field(number: int, *args, packed=True, **kwargs) -> Any:
    """
    Convenience function to assign field numbers.
    Calls the standard ``dataclasses.field`` function with the metadata assigned.
    """
    return dataclasses.field(*args, metadata={'number': number, 'packed': packed}, **kwargs)


def optional_field(number: int, *args, **kwargs) -> Any:
    """
    Convenience function to define a field which is assigned `None` by default.
    """
    return field(number, *args, default=None, **kwargs)


def message(cls: Type[T]) -> Type[TMessage]:
    """
    Returns the same class as was passed in, with additional dunder attributes needed for
    serialization and deserialization.
    """

    type_hints = get_type_hints(cls)

    # Used to list all fields and locate fields by field number.
    cast(Type[TMessage], cls).__protobuf_fields__ = dict(
        make_field(field_.metadata['number'], field_.name, type_hints[field_.name], field_.metadata['packed'])
        for field_ in dataclasses.fields(cls)
    )

    Message.register(cls)  # type: ignore
    cls.serializer = MessageSerializer(cls)  # type: ignore
    cls.type_url = f'type.googleapis.com/{cls.__module__}.{cls.__name__}'  # type: ignore
    cls.validate = Message.validate  # type: ignore
    cls.dump = Message.dump  # type: ignore
    cls.dumps = Message.dumps  # type: ignore
    cls.merge_from = Message.merge_from  # type: ignore
    cls.load = classmethod(load)  # type: ignore
    cls.loads = classmethod(loads)  # type: ignore

    return cast(Type[TMessage], cls)


def make_field(number: int, name: str, type_: Any, packed: bool = True) -> Tuple[int, Field]:
    """
    Figure out how to serialize and de-serialize the field.
    Returns the field number and a corresponding ``Field`` instance.
    """
    is_optional, type_ = get_optional(type_)
    is_repeated, type_ = get_repeated(type_)

    serializer: Serializer
    if isinstance(type_, type) and issubclass(type_, Message):
        # Embedded message.
        serializer = PackingSerializer(type_.serializer)
    elif isinstance(type_, type) and issubclass(type_, IntEnum):
        # Enumeration.
        # See also: https://developers.google.com/protocol-buffers/docs/proto3#enum
        serializer = IntEnumSerializer(type_)
    else:
        # Predefined type.
        try:
            serializer = SERIALIZERS[type_]
        except KeyError as e:
            raise TypeError(f'type is not serializable: {type_}') from e

    if not is_repeated:
        # Non-repeated field.
        return number, NonRepeatedField(number, name, serializer, is_optional)
    elif serializer.wire_type != WireType.BYTES and packed:
        # Repeated fields of scalar numeric types are packed by default.
        # See also: https://developers.google.com/protocol-buffers/docs/encoding#packed
        return number, PackedRepeatedField(number, name, serializer)
    else:
        # Repeated field of other type.
        return number, UnpackedRepeatedField(number, name, serializer)


def get_optional(type_: Any) -> Tuple[bool, Any]:
    """
    Extracts ``Optional`` type annotation if present.
    This may be useful if a user wants to annotate a field with ``Optional[...]`` and set default to ``None``.
    """
    if getattr(type_, '__origin__', None) is Union:
        args = set(type_.__args__)

        # Check if it's a union of `NoneType` and something else.
        if len(args) == 2 and NoneType in args:
            # Extract inner type.
            type_, = args - {NoneType}
            return True, type_

    return False, type_


def get_repeated(type_: Any) -> Tuple[bool, Any]:
    """
    Extracts ``repeated`` modifier if present.
    """
    if getattr(type_, '__origin__', None) in (list, List, Iterable, abc.Iterable):
        type_, = type_.__args__
        return True, type_
    else:
        return False, type_


SERIALIZERS: Dict[Any, Serializer] = {
    bool: serializers.BooleanSerializer(),
    bytes: serializers.bytes_serializer,
    ByteString: serializers.bytes_serializer,
    float: serializers.FloatSerializer(),
    int: serializers.signed_varint_serializer,  # is not a part of the standard
    str: serializers.StringSerializer(),
    types.double: serializers.DoubleSerializer(),
    types.fixed32: serializers.UnsignedFixed32Serializer(),
    types.fixed64: serializers.UnsignedFixed64Serializer(),
    types.sfixed32: serializers.SignedFixed32Serializer(),
    types.sfixed64: serializers.SignedFixed64Serializer(),
    types.sint32: serializers.SignedInt32Serializer(),
    types.sint64: serializers.SignedInt64Serializer(),
    types.uint32: serializers.UnsignedInt32Serializer(),
    types.uint64: serializers.UnsignedInt64Serializer(),
    types.uint: serializers.unsigned_varint_serializer,  # is not a part of the standard
    # TODO: `map`.
}

__all__ = [
    'field',
    'load',
    'loads',
    'message',
    'Message',
]
