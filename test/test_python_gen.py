import base64
import datetime
import json
import unittest

from babelapi.generator.target.python import (
    babel_validators as bv
)
from babelapi.generator.target.python.babel_serializers import (
    json_encode,
    json_decode,
)

class TestPythonGen(unittest.TestCase):
    """
    Tests the Python Generator.
    TODO(kelkabany): Currently tests only the dependencies, and not the
        generated code.
    """

    def test_string_data_type(self):
        s = bv.String(min_length=1, max_length=5, pattern='[A-z]+')
        # Not a string
        self.assertRaises(bv.ValidationError, lambda: s.validate(1))
        # Too short
        self.assertRaises(bv.ValidationError, lambda: s.validate(''))
        # Too long
        self.assertRaises(bv.ValidationError, lambda: s.validate('a'*6))
        # Doesn't pass regex
        self.assertRaises(bv.ValidationError, lambda: s.validate('#'))
        # Passes
        s.validate('a')
        # Check that the validator is converting all strings to unicode
        self.assertEqual(type(s.validate('a')), unicode)

    def test_boolean_data_type(self):
        b = bv.Boolean()
        b.validate(True)
        b.validate(False)
        self.assertRaises(bv.ValidationError, lambda: b.validate(1))

    def test_integer_data_type(self):
        i = bv.UInt32(min_value=10, max_value=100)
        # Not an integer
        self.assertRaises(bv.ValidationError, lambda: i.validate(1.4))
        # Too small
        self.assertRaises(bv.ValidationError, lambda: i.validate(1))
        # Too large
        self.assertRaises(bv.ValidationError, lambda: i.validate(101))
        # Passes
        i.validate(50)

        # min_value is less than the default for the type
        self.assertRaises(ValueError, lambda: bv.UInt32(min_value=-3))
        # non-sensical min_value
        self.assertRaises(AssertionError, lambda: bv.UInt32(min_value=1.3))

    def test_binary_data_type(self):
        b = bv.Binary(min_length=1, max_length=10)
        # Not a valid binary type
        self.assertRaises(bv.ValidationError, lambda: b.validate(u'asdf'))
        # Too short
        self.assertRaises(bv.ValidationError, lambda: b.validate(''))
        # Too long
        self.assertRaises(bv.ValidationError, lambda: b.validate('\x00'*11))
        # Passes
        b.validate('\x00')

    def test_timestamp_data_type(self):
        t = bv.Timestamp('%a, %d %b %Y %H:%M:%S +0000')
        self.assertRaises(bv.ValidationError, lambda: t.validate('abcd'))
        t.validate(datetime.datetime.utcnow())

    def test_list_data_type(self):
        l = bv.List(bv.String(), min_items=1, max_items=10)
        # Not a valid list type
        self.assertRaises(bv.ValidationError, lambda: l.validate('a'))
        # Too short
        self.assertRaises(bv.ValidationError, lambda: l.validate([]))
        # Too long
        self.assertRaises(bv.ValidationError, lambda: l.validate([1]*11))
        # Not a valid string type
        self.assertRaises(bv.ValidationError, lambda: l.validate([1]))
        # Passes
        l.validate(['a'])

    def test_nullable_data_type(self):
        n = bv.Nullable(bv.String())
        # Absent case
        n.validate(None)
        # Fails string validation
        self.assertRaises(bv.ValidationError, lambda: n.validate(123))
        # Passes
        n.validate('abc')
        # Stacking nullables isn't supported by our JSON wire format
        self.assertRaises(AssertionError,
                          lambda: bv.Nullable(bv.Nullable(bv.String())))

    def test_struct_data_type(self):
        class C(object):
            _fields_ = [('f', bv.String())]
            f = None
        s = bv.Struct(C)
        self.assertRaises(bv.ValidationError, lambda: s.validate(object()))

    def test_any_data_type(self):
        a = bv.Any()
        a.validate(object())

    def test_json_encoder(self):
        self.assertEqual(json_encode(bv.String(), 'abc'), json.dumps('abc'))
        self.assertEqual(json_encode(bv.String(), u'\u2650'), json.dumps(u'\u2650'))
        self.assertEqual(json_encode(bv.UInt32(), 123), json.dumps(123))
        # Because a bool is a subclass of an int, ensure they aren't mistakenly
        # encoded as a true/false in JSON when an integer is the data type.
        self.assertEqual(json_encode(bv.UInt32(), True), json.dumps(1))
        self.assertEqual(json_encode(bv.Boolean(), True), json.dumps(True))
        f = '%a, %d %b %Y %H:%M:%S +0000'
        now = datetime.datetime.utcnow()
        self.assertEqual(json_encode(bv.Timestamp('%a, %d %b %Y %H:%M:%S +0000'), now),
                         json.dumps(now.strftime(f)))
        b = '\xff' * 5
        self.assertEqual(json_encode(bv.Binary(), b), json.dumps(base64.b64encode(b)))
        self.assertEqual(json_encode(bv.Nullable(bv.String()), None), json.dumps(None))
        self.assertEqual(json_encode(bv.Nullable(bv.String()), u'abc'), json.dumps('abc'))

    def test_json_encoder_union(self):
        class S(object):
            _field_names_ = {'f'}
            _fields_ = [('f', bv.String())]
        class U(object):
            _tagmap_ = {'a': bv.Int64(),
                        'b': bv.Symbol(),
                        'c': bv.Struct(S),
                        'd': bv.List(bv.Int64()),
                        'e': bv.Nullable(bv.Int64()),
                        'f': bv.Nullable(bv.Struct(S))}
            _tag = None
            def __init__(self, tag, value=None):
                self._tag = tag
                setattr(self, '_' + tag, value)
            def get_a(self):
                return self._a
            def get_c(self):
                return self._c
            def get_d(self):
                return self._d

        U.b = U('b')

        # Test primitive variant
        u = U('a', 64)
        self.assertEqual(json_encode(bv.Union(U), u), json.dumps({'a': 64}))

        # Test symbol variant
        u = U('b')
        self.assertEqual(json_encode(bv.Union(U), u), json.dumps('b'))

        # Test struct variant
        c = S()
        c.f = 'hello'
        c._f_present = True
        u = U('c', c)
        self.assertEqual(json_encode(bv.Union(U), u), json.dumps({'c': {'f': 'hello'}}))

        # Test list variant
        u = U('d', [1, 2, 3, 'a'])
        # lists should be re-validated during serialization
        self.assertRaises(bv.ValidationError, lambda: json_encode(bv.Union(U), u))
        l = [1, 2, 3, 4]
        u = U('d', [1, 2, 3, 4])
        self.assertEqual(json_encode(bv.Union(U), u), json.dumps({'d': l}))

        # Test a nullable union
        self.assertEqual(json_encode(bv.Nullable(bv.Union(U)), None),
                         json.dumps(None))
        self.assertEqual(json_encode(bv.Nullable(bv.Union(U)), u),
                         json.dumps({'d': l}))

        # Test nullable primitive variant
        u = U('e', None)
        self.assertEqual(json_encode(bv.Nullable(bv.Union(U)), u),
                         json.dumps({'e': None}))
        u = U('e', 64)
        self.assertEqual(json_encode(bv.Nullable(bv.Union(U)), u),
                         json.dumps({'e': 64}))

        # Test nullable composite variant
        u = U('f', None)
        self.assertEqual(json_encode(bv.Nullable(bv.Union(U)), u),
                         json.dumps({'f': None}))
        u = U('f', c)
        self.assertEqual(json_encode(bv.Nullable(bv.Union(U)), u),
                         json.dumps({'f': {'f': 'hello'}}))

    def test_json_decoder(self):
        self.assertEqual(json_decode(bv.String(), json.dumps('abc')), 'abc')
        self.assertRaises(bv.ValidationError,
                          lambda: json_decode(bv.String(), json.dumps(32)))

        self.assertEqual(json_decode(bv.UInt32(), json.dumps(123)), 123)
        self.assertRaises(bv.ValidationError,
                          lambda: json_decode(bv.UInt32(), json.dumps('hello')))

        self.assertEqual(json_decode(bv.Boolean(), json.dumps(True)), True)
        self.assertRaises(bv.ValidationError,
                          lambda: json_decode(bv.Boolean(), json.dumps(1)))

        f = '%a, %d %b %Y %H:%M:%S +0000'
        now = datetime.datetime.utcnow().replace(microsecond=0)
        self.assertEqual(json_decode(bv.Timestamp('%a, %d %b %Y %H:%M:%S +0000'),
                                     json.dumps(now.strftime(f))),
                         now)
        b = '\xff' * 5
        self.assertEqual(json_decode(bv.Binary(), json.dumps(base64.b64encode(b))), b)
        self.assertRaises(bv.ValidationError,
                          lambda: json_decode(bv.Binary(), json.dumps(1)))
        self.assertEqual(json_decode(bv.Nullable(bv.String()), json.dumps(None)), None)
        self.assertEqual(json_decode(bv.Nullable(bv.String()), json.dumps('abc')), 'abc')

    def test_json_decoder_union(self):
        class S(object):
            _field_names_ = {'f'}
            _fields_ = [('f', bv.String())]
        class U(object):
            _tagmap_ = {'a': bv.Int64(),
                        'b': bv.Symbol(),
                        'c': bv.Struct(S),
                        'd': bv.List(bv.Int64()),
                        'e': bv.Nullable(bv.Int64()),
                        'f': bv.Nullable(bv.Struct(S))}
            _catch_all_ = 'b'
            _tag = None
            def __init__(self, tag, value=None):
                self._tag = tag
                setattr(self, '_' + tag, value)
            def get_a(self):
                return self._a
            def get_c(self):
                return self._c
            def get_d(self):
                return self._d
        U.b = U('b')

        # Test primitive variant
        u = json_decode(bv.Union(U), json.dumps({'a': 64}))
        self.assertEqual(u.get_a(), 64)

        # Test symbol variant
        u = json_decode(bv.Union(U), json.dumps('b'))
        self.assertEqual(u._tag, 'b')
        self.assertRaises(bv.ValidationError,
                          lambda: json_decode(bv.Union(U), json.dumps([1,2])))

        # Test struct variant
        u = json_decode(bv.Union(U), json.dumps({'c': {'f': 'hello'}}))
        self.assertEqual(u.get_c().f, 'hello')
        self.assertRaises(bv.ValidationError,
                          lambda: json_decode(bv.Union(U), json.dumps({'c': [1,2,3]})))

        # Test list variant
        l = [1, 2, 3, 4]
        u = json_decode(bv.Union(U), json.dumps({'d': l}))
        self.assertEqual(u.get_d(), l)

        # Raises if unknown tag
        self.assertRaises(bv.ValidationError, lambda: json_decode(bv.Union(U), json.dumps('z')))

        # Unknown variant (strict=True)
        self.assertRaises(bv.ValidationError,
                          lambda: json_decode(bv.Union(U), json.dumps({'z': 'test'})))

        # Test catch all variant
        u = json_decode(bv.Union(U), json.dumps({'z': 'test'}), strict=False)
        self.assertEqual(u._tag, 'b')

        # Test nullable union
        u = json_decode(bv.Nullable(bv.Union(U)), json.dumps(None), strict=False)
        self.assertEqual(u, None)

        # Test nullable primitive variant
        u = json_decode(bv.Union(U), json.dumps({'e': None}), strict=False)
        self.assertEqual(u._tag, 'e')
        self.assertEqual(u._e, None)
        u = json_decode(bv.Union(U), json.dumps({'e': 64}), strict=False)
        self.assertEqual(u._tag, 'e')
        self.assertEqual(u._e, 64)

        # Test nullable composite variant
        u = json_decode(bv.Union(U), json.dumps({'f': None}), strict=False)
        self.assertEqual(u._tag, 'f')
        u = json_decode(bv.Union(U), json.dumps({'f': {'f': 'hello'}}), strict=False)
        self.assertEqual(type(u._f), S)
        self.assertEqual(u._f.f, 'hello')
