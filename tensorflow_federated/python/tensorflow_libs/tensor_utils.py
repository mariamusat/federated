# Copyright 2018, The TensorFlow Federated Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""General utilities specific to the manipulation of tensors and operators."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import collections
import functools
import operator

import six
from six.moves import zip
import tensorflow as tf

from tensorflow_federated.python.common_libs import py_typecheck

nest = tf.contrib.framework.nest


def check_nested_equal(nested_x, nested_y, eq_fn=operator.eq):
  """Raises error if two nested structures are not equal.

  Nested structures are equal iff they have the same structure and the values at
  each position are equal.

  Args:
    nested_x: an arbitrarily nested structure.
    nested_y: an arbitrarily nested structure.
    eq_fn: a callable of two parameters that returns True iff the two parameters
      are equal.

  Raises:
    ValueError: If the two structures differ in value at any position in the
      nested structure.
  """
  nest.assert_same_structure(nested_x, nested_y)
  flat_x = nest.flatten(nested_x)
  flat_y = nest.flatten(nested_y)
  for x, y in zip(flat_x, flat_y):
    if not eq_fn(x, y):
      raise ValueError('{x} != {y}'.format(x=x, y=y))


# TODO(b/124544593): Rename to_var_odict for consistency.
def to_var_dict(variables):
  """Returns an `OrderedDict` of `vars`, keyed by names.

  Checks that all variables have unique names. The order of the variables
  is preserved, since this may be important if the values are used as a list
  later, as in keras_model.set_weights().

  Args:
    variables: An iterable of variables.

  Returns:
    A `collections.OrderedDict` keyed by variable name with the ":0" removed.

  """
  tuples = []
  seen_names = set()
  for v in variables:
    py_typecheck.check_type(v, tf.Variable, 'v')
    name = v.name
    if name[-2:] != ':0':
      raise ValueError('Variable has unexpected name {}'.format(v.name))
    name = v.name[:-2]

    if name in seen_names:
      raise ValueError('Found multiple variables with the name', name)
    tuples.append((name, v))
    seen_names.add(name)
  return collections.OrderedDict(tuples)


def to_odict(d):
  """Converts d to an OrderedDict with lexically sorted string keys."""
  if isinstance(d, collections.OrderedDict):
    return d
  py_typecheck.check_type(d, dict)
  items = []
  for k, v in six.iteritems(d):
    py_typecheck.check_type(k, six.string_types)
    items.append((k, v))
  return collections.OrderedDict(sorted(items))


# TODO(b/122081673): autograph was explicitly disabled here to work with TF
# v1.13. Once TFF moves past 1.13, autograh should be able to be renabled and
# the tf.cond() statement replaced with python control flow.
@tf.contrib.eager.function(autograph=False)
def zero_all_if_any_non_finite(structure):
  """Zeroes out all entries in input if any are not finite.

  Args:
    structure: A structure supported by tf.contrib.framework.nest.

  Returns:
     A tuple (input, 0) if all entries are finite or the structure is empty, or
     a tuple (zeros, 1) if any non-finite entries were found.
  """
  flat = nest.flatten(structure)
  if not flat:
    return (structure, tf.constant(0))
  flat_bools = [tf.reduce_all(tf.is_finite(t)) for t in flat]
  all_finite = functools.reduce(tf.logical_and, flat_bools)

  def t_fn():
    return (structure, tf.constant(0))

  def f_fn():
    return (nest.map_structure(tf.zeros_like, structure), tf.constant(1))

  return tf.cond(pred=all_finite, true_fn=t_fn, false_fn=f_fn)


def is_scalar(tensor):
  """Returns True iff the given tensor is a scalar.

  Args:
    tensor: The tensor to test for being a scalar.

  Returns:
    True if 'tensor' is a scalar, i.e. all dims are 1, False otherwise.

  Raises:
    TypeError: when the argument is not a tensor.
  """
  if not tf.contrib.framework.is_tensor(tensor):
    raise TypeError('Expected a tensor, found "{}".'.format(
        py_typecheck.type_string(type(tensor))))
  return (hasattr(tensor, 'get_shape') and
          all(dim == 1 for dim in tensor.get_shape()))


def metrics_sum(values, name=None):
  """A function like tf.metrics.mean, but for a simple sum.

  Args:
    values: A rank-1 tensor to be summed.
    name: Optional name for the op.

  Returns:
    A tuple of:
      sum: A variable holding the current sum of all 'values' seen so far.
      update_op: An opt to run on each minibatch.
  """
  with tf.variable_scope(name, 'metrics_sum', (values,)):
    sum_var = tf.get_variable(
        'sum', [],
        values.dtype,
        initializer=tf.zeros_initializer,
        collections=[tf.GraphKeys.LOCAL_VARIABLES],
        trainable=False)
    update_op = tf.assign_add(sum_var, tf.reduce_sum(values))
    return sum_var, update_op


def same_dimension(x, y):
  """Determines if two `tf.Dimension`s are the same.

  Args:
    x: a `tf.Dimension` object.
    y: a `tf.Dimension` object.

  Returns:
    True iff `x` and `y` are either both _unknown_ (i.e. `None`), or both have
    the same value.
  """
  if x is None:
    return y is None
  else:
    return y is not None and x.value == y.value


def same_shape(x, y):
  """Determines if two `tf.TensorShape`s are the same.

  Args:
    x: a `tf.TensorShape` object.
    y: a `tf.TensorShape` object.

  Returns:
    True iff `x` and `y` are either both _unknonw_ shapes (e.g.
    `tf.TensorShape(None)`) or have each dimension the same.
  """
  if x.ndims != y.ndims:
    return False
  if x.dims is None:
    return y.dims is None
  else:
    return y.dims is not None and all(
        same_dimension(a, b) for a, b in zip(x.dims, y.dims))
