#    Copyright 2013 Red Hat, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import abc
import datetime
from distutils import versionpredicate
import re

import copy
import iso8601
import netaddr
from oslo_utils import strutils
from oslo_utils import timeutils
import six

from oslo_versionedobjects._i18n import _, _LE
from oslo_versionedobjects import _utils
from oslo_versionedobjects import exception


class KeyTypeError(TypeError):
    def __init__(self, expected, value):
        super(KeyTypeError, self).__init__(
            _('Key %(key)s must be of type %(expected)s not %(actual)s'
              ) % {'key': repr(value),
                   'expected': expected.__name__,
                   'actual': value.__class__.__name__,
                   })


class ElementTypeError(TypeError):
    def __init__(self, expected, key, value):
        super(ElementTypeError, self).__init__(
            _('Element %(key)s:%(val)s must be of type %(expected)s'
              ' not %(actual)s'
              ) % {'key': key,
                   'val': repr(value),
                   'expected': expected,
                   'actual': value.__class__.__name__,
                   })


@six.add_metaclass(abc.ABCMeta)
class AbstractFieldType(object):
    @abc.abstractmethod
    def coerce(self, obj, attr, value):
        """This is called to coerce (if possible) a value on assignment.

        This method should convert the value given into the designated type,
        or throw an exception if this is not possible.

        :param:obj: The VersionedObject on which an attribute is being set
        :param:attr: The name of the attribute being set
        :param:value: The value being set
        :returns: A properly-typed value
        """
        pass

    @abc.abstractmethod
    def from_primitive(self, obj, attr, value):
        """This is called to deserialize a value.

        This method should deserialize a value from the form given by
        to_primitive() to the designated type.

        :param:obj: The VersionedObject on which the value is to be set
        :param:attr: The name of the attribute which will hold the value
        :param:value: The serialized form of the value
        :returns: The natural form of the value
        """
        pass

    @abc.abstractmethod
    def to_primitive(self, obj, attr, value):
        """This is called to serialize a value.

        This method should serialize a value to the form expected by
        from_primitive().

        :param:obj: The VersionedObject on which the value is set
        :param:attr: The name of the attribute holding the value
        :param:value: The natural form of the value
        :returns: The serialized form of the value
        """
        pass

    @abc.abstractmethod
    def describe(self):
        """Returns a string describing the type of the field."""
        pass

    @abc.abstractmethod
    def stringify(self, value):
        """Returns a short stringified version of a value."""
        pass


class FieldType(AbstractFieldType):
    @staticmethod
    def coerce(obj, attr, value):
        return value

    @staticmethod
    def from_primitive(obj, attr, value):
        return value

    @staticmethod
    def to_primitive(obj, attr, value):
        return value

    def describe(self):
        return self.__class__.__name__

    def stringify(self, value):
        return str(value)


class UnspecifiedDefault(object):
    pass


class Field(object):
    def __init__(self, field_type, nullable=False,
                 default=UnspecifiedDefault, read_only=False):
        self._type = field_type
        self._nullable = nullable
        self._default = default
        self._read_only = read_only

    def __repr__(self):
        return '%s(default=%s,nullable=%s)' % (self._type.__class__.__name__,
                                               self._default, self._nullable)

    @property
    def nullable(self):
        return self._nullable

    @property
    def default(self):
        return self._default

    @property
    def read_only(self):
        return self._read_only

    def _null(self, obj, attr):
        if self.nullable:
            return None
        elif self._default != UnspecifiedDefault:
            # NOTE(danms): We coerce the default value each time the field
            # is set to None as our contract states that we'll let the type
            # examine the object and attribute name at that time.
            return self._type.coerce(obj, attr, copy.deepcopy(self._default))
        else:
            raise ValueError(_("Field `%s' cannot be None") % attr)

    def coerce(self, obj, attr, value):
        """Coerce a value to a suitable type.

        This is called any time you set a value on an object, like:

          foo.myint = 1

        and is responsible for making sure that the value (1 here) is of
        the proper type, or can be sanely converted.

        This also handles the potentially nullable or defaultable
        nature of the field and calls the coerce() method on a
        FieldType to actually do the coercion.

        :param:obj: The object being acted upon
        :param:attr: The name of the attribute/field being set
        :param:value: The value being set
        :returns: The properly-typed value
        """
        if value is None:
            return self._null(obj, attr)
        else:
            return self._type.coerce(obj, attr, value)

    def from_primitive(self, obj, attr, value):
        """Deserialize a value from primitive form.

        This is responsible for deserializing a value from primitive
        into regular form. It calls the from_primitive() method on a
        FieldType to do the actual deserialization.

        :param:obj: The object being acted upon
        :param:attr: The name of the attribute/field being deserialized
        :param:value: The value to be deserialized
        :returns: The deserialized value
        """
        if value is None:
            return None
        else:
            return self._type.from_primitive(obj, attr, value)

    def to_primitive(self, obj, attr, value):
        """Serialize a value to primitive form.

        This is responsible for serializing a value to primitive
        form. It calls to_primitive() on a FieldType to do the actual
        serialization.

        :param:obj: The object being acted upon
        :param:attr: The name of the attribute/field being serialized
        :param:value: The value to be serialized
        :returns: The serialized value
        """
        if value is None:
            return None
        else:
            return self._type.to_primitive(obj, attr, value)

    def describe(self):
        """Return a short string describing the type of this field."""
        name = self._type.describe()
        prefix = self.nullable and 'Nullable' or ''
        return prefix + name

    def stringify(self, value):
        if value is None:
            return 'None'
        else:
            return self._type.stringify(value)


class String(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        # FIXME(danms): We should really try to avoid the need to do this
        accepted_types = six.integer_types + (float, six.string_types,
                                              datetime.datetime)
        if isinstance(value, accepted_types):
            return six.text_type(value)
        else:
            raise ValueError(_('A string is required in field %(attr)s, '
                               'not a %(type)s') %
                             {'attr': attr, 'type': type(value).__name__})

    @staticmethod
    def stringify(value):
        return '\'%s\'' % value


class SensitiveString(String):
    """A string field type that may contain sensitive (password) information.

    Passwords in the string value are masked when stringified.
    """
    def stringify(self, value):
        return super(SensitiveString, self).stringify(
            strutils.mask_password(value))


class VersionPredicate(String):
    @staticmethod
    def coerce(obj, attr, value):
        try:
            versionpredicate.VersionPredicate('check (%s)' % value)
        except ValueError:
            raise ValueError(_('Version %(val)s is not a valid predicate in '
                               'field %(attr)s') %
                             {'val': value, 'attr': attr})
        return value


class Enum(String):
    def __init__(self, valid_values, **kwargs):
        if not valid_values:
            raise exception.EnumRequiresValidValuesError()
        try:
            # Test validity of the values
            for value in valid_values:
                super(Enum, self).coerce(None, 'init', value)
        except (TypeError, ValueError):
            raise exception.EnumValidValuesInvalidError()
        self._valid_values = valid_values
        super(Enum, self).__init__(**kwargs)

    def coerce(self, obj, attr, value):
        if value not in self._valid_values:
            msg = _("Field value %s is invalid") % value
            raise ValueError(msg)
        return super(Enum, self).coerce(obj, attr, value)

    def stringify(self, value):
        if value not in self._valid_values:
            msg = _("Field value %s is invalid") % value
            raise ValueError(msg)
        return super(Enum, self).stringify(value)


class UUID(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        # FIXME(danms): We should actually verify the UUIDness here
        return str(value)


class MACAddress(FieldType):

    _REGEX = re.compile(r'[0-9a-f]{2}(:[0-9a-f]{2}){5}$')

    @staticmethod
    def coerce(obj, attr, value):
        if isinstance(value, six.string_types):
            lowered = value.lower().replace('-', ':')
            if MACAddress._REGEX.match(lowered):
                return lowered
        raise ValueError(_LE("Malformed MAC %s"), value)


class Integer(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        return int(value)


class Float(FieldType):
    def coerce(self, obj, attr, value):
        return float(value)


class Boolean(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        return bool(value)


class FlexibleBoolean(Boolean):
    @staticmethod
    def coerce(obj, attr, value):
        return strutils.bool_from_string(value)


class DateTime(FieldType):
    def __init__(self, tzinfo_aware=True, *args, **kwargs):
        self.tzinfo_aware = tzinfo_aware
        super(DateTime, self).__init__(*args, **kwargs)

    def coerce(self, obj, attr, value):
        if isinstance(value, six.string_types):
            # NOTE(danms): Being tolerant of isotime strings here will help us
            # during our objects transition
            value = timeutils.parse_isotime(value)
        elif not isinstance(value, datetime.datetime):
            raise ValueError(_('A datetime.datetime is required '
                               'in field %(attr)s, not a %(type)s') %
                             {'attr': attr, 'type': type(value).__name__})

        if value.utcoffset() is None and self.tzinfo_aware:
            # NOTE(danms): Legacy objects from sqlalchemy are stored in UTC,
            # but are returned without a timezone attached.
            # As a transitional aid, assume a tz-naive object is in UTC.
            value = value.replace(tzinfo=iso8601.iso8601.Utc())
        elif not self.tzinfo_aware:
            value = value.replace(tzinfo=None)
        return value

    def from_primitive(self, obj, attr, value):
        return self.coerce(obj, attr, timeutils.parse_isotime(value))

    @staticmethod
    def to_primitive(obj, attr, value):
        return _utils.isotime(value)

    @staticmethod
    def stringify(value):
        return _utils.isotime(value)


class IPAddress(FieldType):
    @staticmethod
    def coerce(obj, attr, value):
        try:
            return netaddr.IPAddress(value)
        except netaddr.AddrFormatError as e:
            raise ValueError(six.text_type(e))

    def from_primitive(self, obj, attr, value):
        return self.coerce(obj, attr, value)

    @staticmethod
    def to_primitive(obj, attr, value):
        return str(value)


class IPV4Address(IPAddress):
    @staticmethod
    def coerce(obj, attr, value):
        result = IPAddress.coerce(obj, attr, value)
        if result.version != 4:
            raise ValueError(_('Network "%(val)s" is not valid '
                               'in field %(attr)s') %
                             {'val': value, 'attr': attr})
        return result


class IPV6Address(IPAddress):
    @staticmethod
    def coerce(obj, attr, value):
        result = IPAddress.coerce(obj, attr, value)
        if result.version != 6:
            raise ValueError(_('Network "%(val)s" is not valid '
                               'in field %(attr)s') %
                             {'val': value, 'attr': attr})
        return result


class IPNetwork(IPAddress):
    @staticmethod
    def coerce(obj, attr, value):
        try:
            return netaddr.IPNetwork(value)
        except netaddr.AddrFormatError as e:
            raise ValueError(six.text_type(e))


class IPV4Network(IPNetwork):
    @staticmethod
    def coerce(obj, attr, value):
        try:
            return netaddr.IPNetwork(value, version=4)
        except netaddr.AddrFormatError as e:
            raise ValueError(six.text_type(e))


class IPV6Network(IPNetwork):
    @staticmethod
    def coerce(obj, attr, value):
        try:
            return netaddr.IPNetwork(value, version=6)
        except netaddr.AddrFormatError as e:
            raise ValueError(six.text_type(e))


class CompoundFieldType(FieldType):
    def __init__(self, element_type, **field_args):
        self._element_type = Field(element_type, **field_args)


class List(CompoundFieldType):
    def coerce(self, obj, attr, value):
        if not isinstance(value, list):
            raise ValueError(_('A list is required in field %(attr)s, '
                               'not a %(type)s') %
                             {'attr': attr, 'type': type(value).__name__})
        coerced_list = CoercedList()
        coerced_list.enable_coercing(self._element_type, obj, attr)
        coerced_list.extend(value)
        return coerced_list

    def to_primitive(self, obj, attr, value):
        return [self._element_type.to_primitive(obj, attr, x) for x in value]

    def from_primitive(self, obj, attr, value):
        return [self._element_type.from_primitive(obj, attr, x) for x in value]

    def stringify(self, value):
        return '[%s]' % (
            ','.join([self._element_type.stringify(x) for x in value]))


class Dict(CompoundFieldType):
    def coerce(self, obj, attr, value):
        if not isinstance(value, dict):
            raise ValueError(_('A dict is required in field %(attr)s, '
                               'not a %(type)s') %
                             {'attr': attr, 'type': type(value).__name__})
        coerced_dict = CoercedDict()
        coerced_dict.enable_coercing(self._element_type, obj, attr)
        coerced_dict.update(value)
        return coerced_dict

    def to_primitive(self, obj, attr, value):
        primitive = {}
        for key, element in value.items():
            primitive[key] = self._element_type.to_primitive(
                obj, '%s["%s"]' % (attr, key), element)
        return primitive

    def from_primitive(self, obj, attr, value):
        concrete = {}
        for key, element in value.items():
            concrete[key] = self._element_type.from_primitive(
                obj, '%s["%s"]' % (attr, key), element)
        return concrete

    def stringify(self, value):
        return '{%s}' % (
            ','.join(['%s=%s' % (key, self._element_type.stringify(val))
                      for key, val in sorted(value.items())]))


class DictProxyField(object):
    """Descriptor allowing us to assign pinning data as a dict of key_types

    This allows us to have an object field that will be a dict of key_type
    keys, allowing that will convert back to string-keyed dict.

    This will take care of the conversion while the dict field will make sure
    that we store the raw json-serializable data on the object.

    key_type should return a type that unambiguously responds to six.text_type
    so that calling key_type on it yields the same thing.
    """
    def __init__(self, dict_field_name, key_type=int):
        self._fld_name = dict_field_name
        self._key_type = key_type

    def __get__(self, obj, obj_type):
        if obj is None:
            return self
        if getattr(obj, self._fld_name) is None:
            return
        return {self._key_type(k): v
                for k, v in six.iteritems(getattr(obj, self._fld_name))}

    def __set__(self, obj, val):
        if val is None:
            setattr(obj, self._fld_name, val)
        else:
            setattr(obj, self._fld_name,
                    {six.text_type(k): v for k, v in six.iteritems(val)})


class Set(CompoundFieldType):
    def coerce(self, obj, attr, value):
        if not isinstance(value, set):
            raise ValueError(_('A set is required in field %(attr)s, '
                               'not a %(type)s') %
                             {'attr': attr, 'type': type(value).__name__})
        coerced_set = CoercedSet()
        coerced_set.enable_coercing(self._element_type, obj, attr)
        coerced_set.update(value)
        return coerced_set

    def to_primitive(self, obj, attr, value):
        return tuple(
            self._element_type.to_primitive(obj, attr, x) for x in value)

    def from_primitive(self, obj, attr, value):
        return set([self._element_type.from_primitive(obj, attr, x)
                    for x in value])

    def stringify(self, value):
        return 'set([%s])' % (
            ','.join([self._element_type.stringify(x) for x in value]))


class Object(FieldType):
    def __init__(self, obj_name, subclasses=False, **kwargs):
        self._obj_name = obj_name
        self._subclasses = subclasses
        super(Object, self).__init__(**kwargs)

    @staticmethod
    def _get_all_obj_names(obj):
        obj_names = []
        for parent in obj.__class__.mro():
            # Skip mix-ins which are not versioned object subclasses
            if not hasattr(parent, "obj_name"):
                continue
            obj_names.append(parent.obj_name())
        return obj_names

    def coerce(self, obj, attr, value):
        try:
            obj_name = value.obj_name()
        except AttributeError:
            obj_name = ""

        if self._subclasses:
            obj_names = self._get_all_obj_names(value)
        else:
            obj_names = [obj_name]

        if self._obj_name not in obj_names:
            raise ValueError(_('An object of type %(type)s is required '
                               'in field %(attr)s, not a %(valtype)s') %
                             {'type': self._obj_name, 'attr': attr,
                              'valtype': obj_name})
        return value

    @staticmethod
    def to_primitive(obj, attr, value):
        return value.obj_to_primitive()

    @staticmethod
    def from_primitive(obj, attr, value):
        # FIXME(danms): Avoid circular import from base.py
        from oslo_versionedobjects import base as obj_base
        # NOTE (ndipanov): If they already got hydrated by the serializer, just
        # pass them back unchanged
        if isinstance(value, obj_base.VersionedObject):
            return value
        return obj.obj_from_primitive(value, obj._context)

    def describe(self):
        return "Object<%s>" % self._obj_name

    def stringify(self, value):
        if 'uuid' in value.fields:
            ident = '(%s)' % (value.obj_attr_is_set('uuid') and value.uuid or
                              'UNKNOWN')
        elif 'id' in value.fields:
            ident = '(%s)' % (value.obj_attr_is_set('id') and value.id or
                              'UNKNOWN')
        else:
            ident = ''

        return '%s%s' % (self._obj_name, ident)


class AutoTypedField(Field):
    AUTO_TYPE = None

    def __init__(self, **kwargs):
        super(AutoTypedField, self).__init__(self.AUTO_TYPE, **kwargs)


class StringField(AutoTypedField):
    AUTO_TYPE = String()


class SensitiveStringField(AutoTypedField):
    """Field type that masks passwords when the field is stringified."""
    AUTO_TYPE = SensitiveString()


class VersionPredicateField(AutoTypedField):
    AUTO_TYPE = VersionPredicate()


class BaseEnumField(AutoTypedField):
    '''Base class for all enum field types

    This class should not be directly instantiated. Instead
    subclass it and set AUTO_TYPE to be a SomeEnum()
    where SomeEnum is a subclass of Enum.
    '''

    def __init__(self, **kwargs):
        if self.AUTO_TYPE is None:
            raise exception.EnumFieldUnset(
                fieldname=self.__class__.__name__)

        if not isinstance(self.AUTO_TYPE, Enum):
            raise exception.EnumFieldInvalid(
                typename=self.AUTO_TYPE.__class__.__name,
                fieldname=self.__class__.__name__)

        super(BaseEnumField, self).__init__(**kwargs)

    def __repr__(self):
        valid_values = self._type._valid_values
        args = {
            'nullable': self._nullable,
            'default': self._default,
            }
        args.update({'valid_values': valid_values})
        return '%s(%s)' % (self._type.__class__.__name__,
                           ','.join(['%s=%s' % (k, v)
                                     for k, v in sorted(args.items())]))


class EnumField(BaseEnumField):
    '''Anonymous enum field type

    This class allows for anonymous enum types to be
    declared, simply by passing in a list of valid values
    to its constructor. It is generally preferrable though,
    to create an explicit named enum type by sub-classing
    the BaseEnumField type directly.
    '''

    def __init__(self, valid_values, **kwargs):
        self.AUTO_TYPE = Enum(valid_values=valid_values)
        super(EnumField, self).__init__(**kwargs)


class UUIDField(AutoTypedField):
    AUTO_TYPE = UUID()


class MACAddressField(AutoTypedField):
    AUTO_TYPE = MACAddress()


class IntegerField(AutoTypedField):
    AUTO_TYPE = Integer()


class FloatField(AutoTypedField):
    AUTO_TYPE = Float()


# This is a strict interpretation of boolean
# values using Python's semantics for truth/falsehood
class BooleanField(AutoTypedField):
    AUTO_TYPE = Boolean()


# This is a flexible interpretation of boolean
# values using common user friendly semantics for
# truth/falsehood. ie strings like 'yes', 'no',
# 'on', 'off', 't', 'f' get mapped to values you
# would expect.
class FlexibleBooleanField(AutoTypedField):
    AUTO_TYPE = FlexibleBoolean()


class DateTimeField(AutoTypedField):
    def __init__(self, tzinfo_aware=True, **kwargs):
        self.AUTO_TYPE = DateTime(tzinfo_aware=tzinfo_aware)
        super(DateTimeField, self).__init__(**kwargs)


class DictOfStringsField(AutoTypedField):
    AUTO_TYPE = Dict(String())


class DictOfNullableStringsField(AutoTypedField):
    AUTO_TYPE = Dict(String(), nullable=True)


class DictOfIntegersField(AutoTypedField):
    AUTO_TYPE = Dict(Integer())


class ListOfStringsField(AutoTypedField):
    AUTO_TYPE = List(String())


class DictOfListOfStringsField(AutoTypedField):
    AUTO_TYPE = Dict(List(String()))


class ListOfEnumField(AutoTypedField):
    def __init__(self, valid_values, **kwargs):
        self.AUTO_TYPE = List(Enum(valid_values))
        super(ListOfEnumField, self).__init__(**kwargs)

    def __repr__(self):
        valid_values = self._type._element_type._type._valid_values
        args = {
            'nullable': self._nullable,
            'default': self._default,
            }
        args.update({'valid_values': valid_values})
        return '%s(%s)' % (self._type.__class__.__name__,
                           ','.join(['%s=%s' % (k, v)
                                     for k, v in sorted(args.items())]))


class SetOfIntegersField(AutoTypedField):
    AUTO_TYPE = Set(Integer())


class ListOfSetsOfIntegersField(AutoTypedField):
    AUTO_TYPE = List(Set(Integer()))


class ListOfDictOfNullableStringsField(AutoTypedField):
    AUTO_TYPE = List(Dict(String(), nullable=True))


class ObjectField(AutoTypedField):
    def __init__(self, objtype, subclasses=False, **kwargs):
        self.AUTO_TYPE = Object(objtype, subclasses)
        self.objname = objtype
        super(ObjectField, self).__init__(**kwargs)


class ListOfObjectsField(AutoTypedField):
    def __init__(self, objtype, subclasses=False, **kwargs):
        self.AUTO_TYPE = List(Object(objtype, subclasses))
        self.objname = objtype
        super(ListOfObjectsField, self).__init__(**kwargs)


class IPAddressField(AutoTypedField):
    AUTO_TYPE = IPAddress()


class IPV4AddressField(AutoTypedField):
    AUTO_TYPE = IPV4Address()


class IPV6AddressField(AutoTypedField):
    AUTO_TYPE = IPV6Address()


class IPNetworkField(AutoTypedField):
    AUTO_TYPE = IPNetwork()


class IPV4NetworkField(AutoTypedField):
    AUTO_TYPE = IPV4Network()


class IPV6NetworkField(AutoTypedField):
    AUTO_TYPE = IPV6Network()


class CoercedCollectionMixin(object):
    def __init__(self, *args, **kwargs):
        self._element_type = None
        self._obj = None
        self._field = None
        super(CoercedCollectionMixin, self).__init__(*args, **kwargs)

    def enable_coercing(self, element_type, obj, field):
        self._element_type = element_type
        self._obj = obj
        self._field = field


class CoercedList(CoercedCollectionMixin, list):
    """List which coerces its elements

    List implementation which overrides all element-adding methods and
    coercing the element(s) being added to the required element type
    """
    def _coerce_item(self, index, item):
        if hasattr(self, "_element_type") and self._element_type is not None:
            att_name = "%s[%i]" % (self._field, index)
            return self._element_type.coerce(self._obj, att_name, item)
        else:
            return item

    def __setitem__(self, i, y):
        if type(i) is slice:  # compatibility with py3 and [::] slices
            start = i.start or 0
            step = i.step or 1
            coerced_items = [self._coerce_item(start + index * step, item)
                             for index, item in enumerate(y)]
            super(CoercedList, self).__setitem__(i, coerced_items)
        else:
            super(CoercedList, self).__setitem__(i, self._coerce_item(i, y))

    def append(self, x):
        super(CoercedList, self).append(self._coerce_item(len(self) + 1, x))

    def extend(self, t):
        l = len(self)
        coerced_items = [self._coerce_item(l + index, item)
                         for index, item in enumerate(t)]
        super(CoercedList, self).extend(coerced_items)

    def insert(self, i, x):
        super(CoercedList, self).insert(i, self._coerce_item(i, x))

    def __iadd__(self, y):
        l = len(self)
        coerced_items = [self._coerce_item(l + index, item)
                         for index, item in enumerate(y)]
        return super(CoercedList, self).__iadd__(coerced_items)

    def __setslice__(self, i, j, y):
        coerced_items = [self._coerce_item(i + index, item)
                         for index, item in enumerate(y)]
        return super(CoercedList, self).__setslice__(i, j, coerced_items)


class CoercedDict(CoercedCollectionMixin, dict):
    """Dict which coerces its values

    Dict implementation which overrides all element-adding methods and
    coercing the element(s) being added to the required element type
    """

    def _coerce_dict(self, d):
        res = {}
        for key, element in six.iteritems(d):
            res[key] = self._coerce_item(key, element)
        return res

    def _coerce_item(self, key, item):
        if not isinstance(key, six.string_types):
            # NOTE(guohliu) In order to keep compatibility with python3
            # we need to use six.string_types rather than basestring here,
            # since six.string_types is a tuple, so we need to pass the
            # real type in.
            raise KeyTypeError(six.string_types[0], key)
        if hasattr(self, "_element_type") and self._element_type is not None:
            att_name = "%s[%s]" % (self._field, key)
            return self._element_type.coerce(self._obj, att_name, item)
        else:
            return item

    def __setitem__(self, key, value):
        super(CoercedDict, self).__setitem__(key,
                                             self._coerce_item(key, value))

    def update(self, other=None, **kwargs):
        if other is not None:
            super(CoercedDict, self).update(self._coerce_dict(other),
                                            **self._coerce_dict(kwargs))
        else:
            super(CoercedDict, self).update(**self._coerce_dict(kwargs))

    def setdefault(self, key, default=None):
        return super(CoercedDict, self).setdefault(key,
                                                   self._coerce_item(key,
                                                                     default))


class CoercedSet(CoercedCollectionMixin, set):
    """Set which coerces its values

    Dict implementation which overrides all element-adding methods and
    coercing the element(s) being added to the required element type
    """
    def _coerce_element(self, element):
        if hasattr(self, "_element_type") and self._element_type is not None:
            return self._element_type.coerce(self._obj,
                                             "%s[%s]" % (self._field, element),
                                             element)
        else:
            return element

    def _coerce_iterable(self, values):
        coerced = set()
        for element in values:
            coerced.add(self._coerce_element(element))
        return coerced

    def add(self, value):
        return super(CoercedSet, self).add(self._coerce_element(value))

    def update(self, values):
        return super(CoercedSet, self).update(self._coerce_iterable(values))

    def symmetric_difference_update(self, values):
        return super(CoercedSet, self).symmetric_difference_update(
            self._coerce_iterable(values))

    def __ior__(self, y):
        return super(CoercedSet, self).__ior__(self._coerce_iterable(y))

    def __ixor__(self, y):
        return super(CoercedSet, self).__ixor__(self._coerce_iterable(y))
