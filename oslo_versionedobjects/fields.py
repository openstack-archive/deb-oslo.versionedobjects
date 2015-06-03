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

import copy
import iso8601
from oslo_utils import timeutils
import six

from oslo_versionedobjects._i18n import _
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
                               'not %(type)s') %
                             {'attr': attr, 'type': value.__class__.__name__})

    @staticmethod
    def stringify(value):
        return '\'%s\'' % value


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
                               'in field %s') % attr)

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
        return timeutils.isotime(value)

    @staticmethod
    def stringify(value):
        return timeutils.isotime(value)


class CompoundFieldType(FieldType):
    def __init__(self, element_type, **field_args):
        self._element_type = Field(element_type, **field_args)


class List(CompoundFieldType):
    def coerce(self, obj, attr, value):
        if not isinstance(value, list):
            raise ValueError(_('A list is required in field %s') % attr)
        for index, element in enumerate(list(value)):
            value[index] = self._element_type.coerce(
                obj, '%s[%i]' % (attr, index), element)
        return value

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
            raise ValueError(_('A dict is required in field %s') % attr)
        for key, element in value.items():
            if not isinstance(key, six.string_types):
                # NOTE(guohliu) In order to keep compatibility with python3
                # we need to use six.string_types rather than basestring here,
                # since six.string_types is a tuple, so we need to pass the
                # real type in.
                raise KeyTypeError(six.string_types[0], key)
            value[key] = self._element_type.coerce(
                obj, '%s["%s"]' % (attr, key), element)
        return value

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

    def __get__(self, obj, obj_type=None):
        if obj is None:
            return self
        if getattr(obj, self._fld_name) is None:
            return
        return dict([(self._key_type(k), v)
                     for k, v in six.iteritems(getattr(obj, self._fld_name))])

    def __set__(self, obj, val):
        if val is None:
            setattr(obj, self._fld_name, val)
        else:
            setattr(obj, self._fld_name,
                    dict([(six.text_type(k), v)
                          for k, v in six.iteritems(val)]))


class Set(CompoundFieldType):
    def coerce(self, obj, attr, value):
        if not isinstance(value, set):
            raise ValueError(_('A set is required in field %s') % attr)

        coerced = set()
        for element in value:
            coerced.add(self._element_type.coerce(
                obj, '%s["%s"]' % (attr, element), element))
        return coerced

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
    def __init__(self, obj_name, **kwargs):
        self._obj_name = obj_name
        super(Object, self).__init__(**kwargs)

    def coerce(self, obj, attr, value):
        try:
            obj_name = value.obj_name()
        except AttributeError:
            obj_name = ""

        if obj_name != self._obj_name:
            raise ValueError(_('An object of type %(type)s is required '
                               'in field %(attr)s') %
                             {'type': self._obj_name, 'attr': attr})
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
        return obj_base.VersionedObject.obj_from_primitive(value, obj._context)

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


class EnumField(AutoTypedField):
    def __init__(self, valid_values, **kwargs):
        self.AUTO_TYPE = Enum(valid_values)
        super(EnumField, self).__init__(**kwargs)

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


class UUIDField(AutoTypedField):
    AUTO_TYPE = UUID()


class IntegerField(AutoTypedField):
    AUTO_TYPE = Integer()


class FloatField(AutoTypedField):
    AUTO_TYPE = Float()


class BooleanField(AutoTypedField):
    AUTO_TYPE = Boolean()


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
    def __init__(self, objtype, **kwargs):
        self.AUTO_TYPE = Object(objtype)
        super(ObjectField, self).__init__(**kwargs)


class ListOfObjectsField(AutoTypedField):
    def __init__(self, objtype, **kwargs):
        self.AUTO_TYPE = List(Object(objtype))
        super(ListOfObjectsField, self).__init__(**kwargs)
