"""
Code generator for Python.
"""

import os
import re
import shutil
from babelapi.data_type import (
    is_any_type,
    is_binary_type,
    is_boolean_type,
    is_composite_type,
    is_float_type,
    is_integer_type,
    is_list_type,
    is_null_type,
    is_string_type,
    is_struct_type,
    is_symbol_type,
    is_tag_ref,
    is_timestamp_type,
    is_union_type,
)
from babelapi.generator.generator import CodeGeneratorMonolingual
from babelapi.lang.python import PythonTargetLanguage

# This will be at the top of every generated file.
base = """\
# Auto-generated by BabelAPI, do not modify.
try:
    from . import babel_validators as bv
except (SystemError, ValueError):
    # Catch errors raised when importing a relative module when not in a package.
    # This makes testing this file directly (outside of a package) easier.
    import babel_validators as bv

"""

# Matches format of Babel doc tags
doc_sub_tag_re = re.compile(':(?P<tag>[A-z]*):`(?P<val>.*?)`')

class PythonGenerator(CodeGeneratorMonolingual):
    """Generates Python modules to represent the input Babel spec."""

    lang = PythonTargetLanguage()

    def generate(self):
        """
        Generates a module for each namespace.

        Each namespace will have Python classes to represent data types and
        routes in the Babel spec.
        """
        cur_folder = os.path.dirname(__file__)
        self._logger.info('Copying babel_validators.py to output folder')
        shutil.copy(os.path.join(cur_folder, 'babel_validators.py'),
                    self.target_folder_path)
        self._logger.info('Copying babel_serializers.py to output folder')
        shutil.copy(os.path.join(cur_folder, 'babel_serializers.py'),
                    self.target_folder_path)
        for namespace in self.api.namespaces.values():
            with self.output_to_relative_path('{}.py'.format(namespace.name)):
                self._generate_base_namespace_module(namespace)

    def _generate_base_namespace_module(self, namespace):
        """Creates a module for the namespace. All data types and routes are
        represented as Python classes."""
        self.emit(base)
        for data_type in namespace.linearize_data_types():
            if is_struct_type(data_type):
                self._generate_struct_class(data_type)
            elif is_union_type(data_type):
                self._generate_union_class(data_type)
            else:
                raise TypeError('Cannot handle type %r' % type(data_type))
        self._generate_routes(namespace)

    def emit_wrapped_indented_lines(self, s):
        """Emits wrapped lines. All lines are the first are indented."""
        self.emit_wrapped_lines(s,
                                prefix='    ',
                                first_line_prefix=False)

    def docf(self, doc):
        """
        Substitutes tags in Babel docs with their Python-doc-friendly
        counterparts. A tag has the following format:

        :<tag>:`<value>`

        Example tags are 'route' and 'struct'.
        """
        if not doc:
            return
        for match in doc_sub_tag_re.finditer(doc):
            matched_text = match.group(0)
            tag = match.group('tag')
            val = match.group('val')
            if tag == 'struct':
                doc = doc.replace(matched_text, ':class:`{}`'.format(val))
            elif tag == 'route':
                doc = doc.replace(matched_text, val)
            elif tag == 'link':
                anchor, link = val.rsplit(' ', 1)
                doc = doc.replace(matched_text, '`{} <{}>`_'.format(anchor, link))
            elif tag == 'val':
                doc = doc.replace(matched_text, '{}'.format(self.lang.format_obj(val)))
            else:
                doc = doc.replace(matched_text, '``{}``'.format(val))
        return doc

    def _python_type_mapping(self, data_type):
        """Map Babel data types to their most natural equivalent in Python
        for documentation purposes."""
        if is_string_type(data_type):
            return 'str'
        elif is_binary_type(data_type):
            return 'str'
        elif is_boolean_type(data_type):
            return 'bool'
        elif is_float_type(data_type):
            return 'float'
        elif is_integer_type(data_type):
            return 'long'
        elif is_null_type(data_type):
            return 'None'
        elif is_timestamp_type(data_type):
            return 'datetime.datetime'
        elif is_composite_type(data_type):
            return self._class_name_for_data_type(data_type)
        elif is_list_type(data_type):
            # PyCharm understands this description format for a list
            return 'list of [{}]'.format(self._python_type_mapping(data_type.data_type))
        else:
            raise TypeError('Unknown data type %r' % data_type)

    def _class_name_for_data_type(self, data_type):
        assert is_composite_type(data_type), \
            'Expected composite type, got %r' % type(data_type)
        return self.lang.format_class(data_type.name)

    #
    # Struct Types
    #

    def _class_declaration_for_struct(self, data_type):
        assert is_struct_type(data_type), \
            'Expected struct, got %r' % type(data_type)
        if data_type.supertype:
            extends = self._class_name_for_data_type(data_type.supertype)
        else:
            extends = 'object'
        return 'class {}({}):'.format(
            self._class_name_for_data_type(data_type), extends)

    def _generate_struct_class(self, data_type):
        """Defines a Python class that represents a struct in Babel."""
        self.emit_line(self._class_declaration_for_struct(data_type))
        with self.indent():
            if data_type.doc:
                self.emit_line('"""')
                self.emit_wrapped_lines(self.docf(data_type.doc))
                self.emit_empty_line()
                for field in data_type.fields:
                    if field.doc:
                        self.emit_wrapped_indented_lines(':ivar {}: {}'.format(
                            self.lang.format_variable(field.name),
                            self.docf(field.doc),
                        ))
                self.emit_line('"""')
            self.emit_empty_line()

            self._generate_struct_class_slots(data_type)
            self._generate_struct_class_vars(data_type)
            self._generate_struct_class_init(data_type)
            self._generate_struct_class_properties(data_type)
            self._generate_struct_class_repr(data_type)

    def _func_args_from_dict(self, d):
        """Given a Python dictionary, creates a string representing arguments
        for invoking a function. All arguments with a value of None are
        ignored."""
        filtered_d = self._filter_out_none_valued_keys(d)
        return ', '.join(['%s=%s' % (k, v) for k, v in filtered_d.items()])

    def _generate_struct_class_slots(self, data_type):
        """Creates a slots declaration for struct classes.

        Slots are an optimization in Python. They reduce the memory footprint
        of instances since attributes cannot be added after declaration.
        """
        self.emit_line('__slots__ = [')
        with self.indent():
            for field in data_type.fields:
                field_name = self.lang.format_variable(field.name)
                self.emit_line("'_%s_value'," % field_name)
                self.emit_line("'_%s_present'," % field_name)
        self.emit_line(']')
        self.emit_empty_line()

    def _generate_struct_class_vars(self, data_type):
        """
        Each class has a class attribute for each field. The attribute is a
        validator for the field.
        """
        lineno = self.lineno
        for field in data_type.fields:
            field_name = self.lang.format_variable(field.name)
            validator_name = self._determine_validator_type(field.data_type)
            self.emit_line('_{}_validator = {}'.format(field_name,
                                                       validator_name))
        if lineno != self.lineno:
            self.emit_empty_line()

        self._generate_struct_class_fields_for_reflection(data_type)

    def _determine_validator_type(self, data_type):
        """
        Given a Babel data type, returns a string that can be used to construct
        the appropriate validation object in Python.
        """
        if is_list_type(data_type):
            v ='bv.List({})'.format(
                self._func_args_from_dict({
                    'item_validator': self._determine_validator_type(data_type.data_type),
                    'min_items': data_type.min_items,
                    'max_items': data_type.max_items,
                })
            )
        elif is_float_type(data_type):
            v = 'bv.{}({})'.format(
                data_type.name,
                self._func_args_from_dict({
                    'min_value': data_type.min_value,
                    'max_value': data_type.max_value,
                })
            )
        elif is_integer_type(data_type):
            v = 'bv.{}({})'.format(
                data_type.name,
                self._func_args_from_dict({
                    'min_value': data_type.min_value,
                    'max_value': data_type.max_value,
                })
            )
        elif is_string_type(data_type):
            v = 'bv.String({})'.format(
                self._func_args_from_dict({
                    'min_length': data_type.min_length,
                    'max_length': data_type.max_length,
                    'pattern': repr(data_type.pattern),
                })
            )
        elif is_timestamp_type(data_type):
            v = 'bv.Timestamp({})'.format(
                self._func_args_from_dict({
                    'format': repr(data_type.format),
                })
            )
        elif is_struct_type(data_type):
            v = 'bv.Struct({})'.format(
                self.lang.format_class(data_type.name),
            )
        elif is_union_type(data_type):
            v = 'bv.Union({})'.format(
                self.lang.format_class(data_type.name),
            )
        else:
            v = 'bv.{}()'.format(
                data_type.name,
            )
        if data_type.nullable:
            return 'bv.Nullable({})'.format(v)
        else:
            return v

    def _generate_struct_class_fields_for_reflection(self, data_type):
        """
        Declares a _field_names_ class attribute, which is a set of all field
        names. Also, declares a _fields_ class attribute which is a list of
        tuples, where each tuple is (field name, validator).
        """
        if data_type.supertype:
            supertype_class_name = self._class_name_for_data_type(data_type.supertype)
        else:
            supertype_class_name = None

        if supertype_class_name:
            self.emit_line('_field_names_ = %s._field_names_.union(set((' %
                           supertype_class_name)
        else:
            self.emit_line('_field_names_ = set((')
        with self.indent():
            for field in data_type.fields:
                self.emit_line("'{}',".format(self.lang.format_variable(field.name)))

        if supertype_class_name:
            self.emit_line(')))')
        else:
            self.emit_line('))')
        self.emit_empty_line()

        if supertype_class_name:
            self.emit_line('_fields_ = {}._fields_ + ['.format(supertype_class_name))
        else:
            self.emit_line('_fields_ = [')

        with self.indent():
            for field in data_type.fields:
                var_name = self.lang.format_variable(field.name)
                validator_name = '_{0}_validator'.format(var_name)
                self.emit_line("('{}', {}),".format(var_name, validator_name))
        self.emit_line(']')
        self.emit_empty_line()

    def _generate_struct_class_init(self, data_type):
        """
        Generates constructor. The constructor takes all possible fields as
        optional arguments. Any argument that is set on construction sets the
        corresponding field for the instance.
        """
        # __init__ signature
        self.emit_line('def __init__', trailing_newline=False)
        args = ['self']
        for field in data_type.all_fields:
            field_name_reserved_check = self.lang.format_variable(field.name, True)
            args.append('%s=None' % field_name_reserved_check)
        self._generate_func_arg_list(args)
        self.emit(':')
        self.emit_empty_line()

        with self.indent():
            lineno = self.lineno

            # Call the parent constructor if a super type exists
            if data_type.supertype:
                class_name = self._class_name_for_data_type(data_type)
                self.emit_line('super({}, self).__init__'.format(class_name),
                               trailing_newline=False)
                self._generate_func_arg_list([self.lang.format_method(f.name, True)
                                              for f in data_type.supertype.fields])
                self.emit_empty_line()

            # initialize each field
            for field in data_type.fields:
                field_var_name = self.lang.format_variable(field.name)
                self.emit_line('self._{}_value = None'.format(field_var_name))
                self.emit_line('self._{}_present = False'.format(field_var_name))

            # handle arguments that were set
            for field in data_type.fields:
                field_var_name = self.lang.format_variable(field.name, True)
                self.emit_line('if {} is not None:'.format(field_var_name))
                with self.indent():
                    self.emit_line('self.{0} = {0}'.format(field_var_name))

            if lineno == self.lineno:
                self.emit_line('pass')
            self.emit_empty_line()

    def _generate_python_value(self, value):
        if is_tag_ref(value):
            return '{}.{}'.format(
                self._class_name_for_data_type(value.union_data_type),
                self.lang.format_variable(value.tag_name))
        else:
            return self.lang.format_obj(value)

    def _generate_struct_class_properties(self, data_type):
        """
        Each field of the struct has a corresponding setter and getter.
        The setter validates the value being set.
        """
        for field in data_type.fields:
            field_name = self.lang.format_method(field.name)
            field_name_reserved_check = self.lang.format_method(field.name, True)

            # generate getter for field
            self.emit_line('@property')
            self.emit_line('def {}(self):'.format(field_name_reserved_check))
            with self.indent():
                self.emit_line('"""')
                if field.doc:
                    self.emit_wrapped_lines(self.docf(field.doc))
                self.emit_line(':rtype: {}'.format(self._python_type_mapping(field.data_type)))
                self.emit_line('"""')
                self.emit_line('if self._{}_present:'.format(field_name))
                with self.indent():
                    self.emit_line('return self._{}_value'.format(field_name))

                self.emit_line('else:')
                with self.indent():
                    if field.data_type.nullable:
                        self.emit_line('return None')
                    elif field.has_default:
                        self.emit_line('return {}'.format(
                            self._generate_python_value(field.default)))
                    else:
                        self.emit_line(
                            'raise AttributeError("missing required field %r")'
                            % field_name
                        )
            self.emit_empty_line()

            # generate setter for field
            self.emit_line('@{}.setter'.format(field_name_reserved_check))
            self.emit_line('def {}(self, val):'.format(field_name_reserved_check))
            with self.indent():
                if field.data_type.nullable:
                    self.emit_line('if val is None:')
                    with self.indent():
                        self.emit_line('del self.{}'.format(field_name_reserved_check))
                        self.emit_line('return')
                if is_composite_type(field.data_type):
                    self.emit_line('self._%s_validator.validate_type_only(val)'
                                   % field_name)
                else:
                    self.emit_line('val = self._{}_validator.validate(val)'.format(field_name))
                self.emit_line('self._{}_value = val'.format(field_name))
                self.emit_line('self._{}_present = True'.format(field_name))
            self.emit_empty_line()

            # generate deleter for field
            self.emit_line('@{}.deleter'.format(field_name_reserved_check))
            self.emit_line('def {}(self):'.format(field_name_reserved_check))
            with self.indent():
                self.emit_line('self._{}_value = None'.format(field_name))
                self.emit_line('self._{}_present = False'.format(field_name))
            self.emit_empty_line()

    def _generate_struct_class_repr(self, data_type):
        """
        Generates something like:

            def __repr__(self):
                return 'Employee(first_name={!r}, last_name={!r}, age={!r})'.format(
                    self._first_name_value,
                    self._last_name_value,
                    self._age_value,
                )
        """
        self.emit_line('def __repr__(self):')
        with self.indent():
            if data_type.all_fields:
                constructor_kwargs_fmt = ', '.join(
                    '{}={{!r}}'.format(self.lang.format_variable(f.name, True))
                    for f in data_type.all_fields)
                self.emit_line("return '{}({})'.format(".format(
                    self._class_name_for_data_type(data_type),
                    constructor_kwargs_fmt,
                ))
                with self.indent():
                    for f in data_type.all_fields:
                        self.emit_line("self._{}_value,".format(self.lang.format_variable(f.name)))
                self.emit_line(")")
            else:
                self.emit_line("return '%s()'"
                               % self._class_name_for_data_type(data_type))
        self.emit_empty_line()

    #
    # Tagged Union Types
    #
    
    def _class_declaration_for_union(self, data_type):
        assert is_union_type(data_type), \
            'Expected union, got %r' % type(data_type)
        if data_type.subtype:
            extends = self._class_name_for_data_type(data_type.subtype)
        else:
            extends = 'object'
        return 'class {}({}):'.format(
            self._class_name_for_data_type(data_type), extends)

    def _generate_union_class(self, data_type):
        """Defines a Python class that represents a union in Babel."""
        self.emit_line(self._class_declaration_for_union(data_type))
        with self.indent():
            if data_type.doc:
                self.emit_line('"""')
                self.emit_wrapped_lines(self.docf(data_type.doc))
                self.emit_empty_line()
                for field in data_type.fields:
                    if is_symbol_type(field.data_type) or is_any_type(field.data_type):
                        ivar_doc = ':ivar {}: {}'.format(
                            self.lang.format_variable(field.name), self.docf(field.doc))
                    elif is_composite_type(field.data_type):
                        ivar_doc = ':ivar {} {}: {}'.format(
                            self.lang.format_class(field.data_type.name),
                            self.lang.format_variable(field.name),
                            self.docf(field.doc))
                    else:
                        ivar_doc = ':ivar {} {}: {}'.format(
                            self._python_type_mapping(field.data_type),
                            self.lang.format_variable(field.name), field.doc)
                    self.emit_wrapped_indented_lines(ivar_doc)
                self.emit_line('"""')
            self.emit_empty_line()

            self._generate_union_class_vars(data_type)
            self._generate_union_class_init(data_type)
            self._generate_union_class_variant_creators(data_type)
            self._generate_union_class_is_set(data_type)
            self._generate_union_class_get_helpers(data_type)
            self._generate_union_class_repr(data_type)
        self._generate_union_class_symbol_creators(data_type)

    def _generate_union_class_vars(self, data_type):
        """
        Each class has a class attribute for each field specifying its data type.
        If a catch all field exists, it's specified as a _catch_all_ attribute.
        """
        lineno = self.lineno
        for field in data_type.fields:
            field_name = self.lang.format_variable(field.name)
            validator_name = self._determine_validator_type(field.data_type)
            self.emit_line('_{}_validator = {}'.format(field_name,
                                                        validator_name))
        if data_type.catch_all_field:
            self.emit_line('_catch_all_ = %r' % data_type.catch_all_field.name)
        elif not data_type.subtype:
            self.emit_line('_catch_all_ = None')

        # Generate stubs for class variables so that IDEs like PyCharms have an
        # easier time detecting their existence.
        for field in data_type.fields:
            if is_symbol_type(field.data_type) or is_any_type(field.data_type):
                field_name = self.lang.format_variable(field.name)
                self.emit_line('# Attribute is overwritten below the class definition')
                self.emit_line('{} = None'.format(field_name))

        if lineno != self.lineno:
            self.emit_empty_line()

        self._generate_union_class_tagmap_for_reflection(data_type)

    def _generate_union_class_tagmap_for_reflection(self, data_type):
        self.emit_line('_tagmap_ = {')
        with self.indent():
            for field in data_type.fields:
                var_name = self.lang.format_variable(field.name)
                validator_name = '_{0}_validator'.format(var_name)
                self.emit_line("'{}': {},".format(var_name, validator_name))
        self.emit_line('}')
        if data_type.subtype:
            self.emit_line('_tagmap_.update({}._tagmap_)'.format(
                self._class_name_for_data_type(data_type.subtype)))
        self.emit_empty_line()

    def _generate_union_class_init(self, data_type):
        """Generates the __init__ method for the class. The tag should be
        specified as a string, and the value will be validated with respect
        to the tag."""
        self.emit_line('def __init__(self, tag, value=None):')
        with self.indent():
            for field in data_type.all_fields:
                field_var_name = self.lang.format_variable(field.name)
                if not is_symbol_type(field.data_type) and not is_any_type(field.data_type):
                    self.emit_line('self._{} = None'.format(field_var_name))
            self.emit_line("assert tag in self._tagmap_, 'Invalid tag %r.' % tag")
            self.emit_line('if isinstance(self._tagmap_[tag], (bv.Any, bv.Symbol)):')
            with self.indent():
                self.emit_line(
                    "assert value is None, 'Do not set a value for Symbol or Any variant.'")
            self.emit_line('else:')
            with self.indent():
                self.emit_line('self._tagmap_[tag].validate(value)')
            self.emit_line("setattr(self, '_' + tag, value)")
            self.emit_line('self._tag = tag')
            self.emit_empty_line()

    def _generate_union_class_variant_creators(self, data_type):
        """
        Each non-symbol, non-any variant has a corresponding class method that
        can be used to construct a union with that variant selected.
        """
        for field in data_type.fields:
            if not is_symbol_type(field.data_type) and not is_any_type(field.data_type):
                field_name = self.lang.format_method(field.name)
                field_name_reserved_check = self.lang.format_method(field.name, True)
                self.emit_line('@classmethod')
                self.emit_line('def {}(cls, val):'.format(field_name_reserved_check))
                with self.indent():
                    self.emit_line('return cls({!r}, val)'.format(field_name))
                self.emit_empty_line()

    def _generate_union_class_is_set(self, data_type):
        for field in data_type.fields:
            field_name = self.lang.format_method(field.name)
            self.emit_line('def is_{}(self):'.format(field_name))
            with self.indent():
                self.emit_line('return self._tag == {!r}'.format(field_name))
            self.emit_empty_line()

    def _generate_union_class_get_helpers(self, data_type):
        """
        These are the getters used to access the value of a variant, once
        the tag has been switched on.
        """
        for field in data_type.fields:
            field_name = self.lang.format_method(field.name)

            if not is_symbol_type(field.data_type) and not is_any_type(field.data_type):
                # generate getter for field
                self.emit_line('def get_{}(self):'.format(field_name))
                with self.indent():
                    self.emit_line('if not self.is_{}():'.format(field_name))
                    with self.indent():
                        self.emit_line('raise AttributeError("tag {!r} not set")'.format(
                            field_name))
                    self.emit_line('return self._{}'.format(field_name))
                self.emit_empty_line()

    def _generate_union_class_repr(self, data_type):
        """
        The __repr__() function will return a string of the class name, and
        the selected tag.
        """
        self.emit_line('def __repr__(self):')
        with self.indent():
            if data_type.fields:
                self.emit_line("return '{}(%r)' % self._tag".format(
                    self._class_name_for_data_type(data_type),
                ))
            else:
                self.emit_line("return '{}()'".format(self._class_name_for_data_type(data_type)))
        self.emit_empty_line()

    def _generate_union_class_symbol_creators(self, data_type):
        """
        Class attributes that represent a symbol are set after the union class
        definition.
        """
        class_name = self.lang.format_class(data_type.name)
        lineno = self.lineno
        for field in data_type.fields:
            if is_symbol_type(field.data_type) or is_any_type(field.data_type):
                field_name = self.lang.format_method(field.name)
                self.emit_line('{0}.{1} = {0}({1!r})'.format(class_name, field_name))
        if lineno != self.lineno:
            self.emit_empty_line()

    #
    # Routes
    #

    STYLE_MAPPING = {
        # Maps from the 'style' attr in the Babel file to the FunctionStyle enum values.
        None: 'RPC',
        'upload': 'UPLOAD',
        'download': 'DOWNLOAD',
    }

    def _generate_routes(self, namespace):
        self.emit_line('FUNCTIONS = {')
        for route in namespace.routes:
            with self.indent():

                host_ident = route.attrs.get('host')
                if host_ident is None:
                    host_ident = 'meta'

                style_enum = self.STYLE_MAPPING[route.attrs.get('style')]
                self.emit_line('{!r}: ({!r}, bv.FunctionSignature('.format(route.name, host_ident))
                with self.indent():
                    self.emit_line('bv.FunctionStyle.{},'.format(style_enum))
                    for t in (route.request_data_type, route.response_data_type, route.error_data_type):
                        self.emit_line('{},'.format(self._determine_validator_type(t)))
                self.emit_line(')),')
        self.emit_line('}')
