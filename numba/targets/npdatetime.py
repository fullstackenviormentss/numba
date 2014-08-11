"""
Implementation of operations on numpy timedelta64.
"""

from llvm.core import Type, Constant
import llvm.core as lc

from numba import npdatetime, types, typing, cgutils, utils
from numba.targets.imputils import (builtin, builtin_attr, implement,
                                    impl_attribute, impl_attribute_generic,
                                    iterator_impl, iternext_impl,
                                    struct_factory, type_factory)
from numba.typing import signature


TIMEDELTA64 = Type.int(64)
NAT = Constant.int(TIMEDELTA64, npdatetime.NAT)


@type_factory(types.NPTimedelta)
def llvm_timedelta_type(context, tp):
    return TIMEDELTA64


TIMEDELTA_BINOP_SIG = (types.Kind(types.NPTimedelta),) * 2

def scale_timedelta(context, builder, val, srcty, destty):
    """
    Scale the timedelta64 *val* from *srcty* to *destty*
    (both numba.types.NPTimedelta instances)
    """
    factor = npdatetime.get_timedelta_conversion_factor(srcty.unit, destty.unit)
    return builder.mul(Constant.int(TIMEDELTA64, factor), val)

def alloc_timedelta_result(builder, name='ret'):
    """
    Allocate a NaT-initialized timedelta64 result slot.
    """
    ret = cgutils.alloca_once(builder, TIMEDELTA64, name)
    builder.store(NAT, ret)
    return ret

def is_not_nat(builder, val):
    return builder.icmp(lc.ICMP_NE, val, NAT)

def are_not_nat(builder, vals):
    assert len(vals) >= 1
    pred = is_not_nat(builder, vals[0])
    for val in vals[1:]:
        pred = builder.and_(pred, is_not_nat(builder, val))
    return pred


@builtin
@implement('+', *TIMEDELTA_BINOP_SIG)
def timedelta_add_impl(context, builder, sig, args):
    [va, vb] = args
    [ta, tb] = sig.args
    ret = alloc_timedelta_result(builder)
    with cgutils.if_likely(builder, are_not_nat(builder, [va, vb])):
        va = scale_timedelta(context, builder, va, ta, sig.return_type)
        vb = scale_timedelta(context, builder, vb, tb, sig.return_type)
        builder.store(builder.add(va, vb), ret)
    return builder.load(ret)

@builtin
@implement('-', *TIMEDELTA_BINOP_SIG)
def timedelta_sub_impl(context, builder, sig, args):
    [va, vb] = args
    [ta, tb] = sig.args
    ret = alloc_timedelta_result(builder)
    with cgutils.if_likely(builder, are_not_nat(builder, [va, vb])):
        va = scale_timedelta(context, builder, va, ta, sig.return_type)
        vb = scale_timedelta(context, builder, vb, tb, sig.return_type)
        builder.store(builder.sub(va, vb), ret)
    return builder.load(ret)


def timedelta_times_number(context, builder, td_arg, number_arg, number_type):
    ret = alloc_timedelta_result(builder)
    with cgutils.if_likely(builder, is_not_nat(builder, td_arg)):
        if isinstance(number_type, types.Float):
            val = builder.sitofp(td_arg, number_arg.type)
            val = builder.fmul(val, number_arg)
            val = builder.fptosi(val, TIMEDELTA64)
        else:
            val = builder.mul(td_arg, number_arg)
        builder.store(val, ret)
    return builder.load(ret)

@builtin
@implement('*', types.Kind(types.NPTimedelta), types.Kind(types.Integer))
@implement('*', types.Kind(types.NPTimedelta), types.Kind(types.Float))
def timedelta_mul_impl(context, builder, sig, args):
    return timedelta_times_number(context, builder,
                                  args[0], args[1], sig.args[1])

@builtin
@implement('*', types.Kind(types.Integer), types.Kind(types.NPTimedelta))
@implement('*', types.Kind(types.Float), types.Kind(types.NPTimedelta))
def timedelta_mul_impl(context, builder, sig, args):
    return timedelta_times_number(context, builder,
                                  args[1], args[0], sig.args[0])

@builtin
@implement('/', types.Kind(types.NPTimedelta), types.Kind(types.Integer))
@implement('//', types.Kind(types.NPTimedelta), types.Kind(types.Integer))
@implement('/', types.Kind(types.NPTimedelta), types.Kind(types.Float))
@implement('//', types.Kind(types.NPTimedelta), types.Kind(types.Float))
def timedelta_div_impl(context, builder, sig, args):
    td_arg, number_arg = args
    number_type = sig.args[1]
    ret = alloc_timedelta_result(builder)
    ok = builder.and_(is_not_nat(builder, td_arg),
                      builder.not_(cgutils.is_scalar_zero(builder, number_arg)))
    with cgutils.if_likely(builder, ok):
        if isinstance(number_type, types.Float):
            val = builder.sitofp(td_arg, number_arg.type)
            val = builder.fdiv(val, number_arg)
            val = builder.fptosi(val, TIMEDELTA64)
        else:
            val = builder.sdiv(td_arg, number_arg)
        builder.store(val, ret)
    return builder.load(ret)

@builtin
@implement('/', types.Kind(types.NPTimedelta), types.Kind(types.NPTimedelta))
@implement('/?', types.Kind(types.NPTimedelta), types.Kind(types.NPTimedelta))
def timedelta_div_impl(context, builder, sig, args):
    [va, vb] = args
    [ta, tb] = sig.args
    not_nan = are_not_nat(builder, [va, vb])
    ll_ret_type = context.get_value_type(sig.return_type)
    ret = cgutils.alloca_once(builder, ll_ret_type, 'ret')
    builder.store(Constant.real(ll_ret_type, float('nan')), ret)
    with cgutils.if_likely(builder, not_nan):
        if tb.unit < ta.unit:
            vb = scale_timedelta(context, builder, vb, tb, ta)
        else:
            va = scale_timedelta(context, builder, va, ta, tb)
        va = builder.sitofp(va, ll_ret_type)
        vb = builder.sitofp(vb, ll_ret_type)
        builder.store(builder.fdiv(va, vb), ret)
    return builder.load(ret)

