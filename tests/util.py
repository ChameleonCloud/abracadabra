def _single(iterable):
    '''Guarantee there is only one value in *iterable* and returns it'''
    it = iter(iterable)
    try:
        val = next(it)
    except StopIteration:
        raise ValueError('no items in iterable')

    try:
        next(it)
    except StopIteration:
        pass
    else:
        raise ValueError('more than one item in the iterable')
    return val


def single(iterable):
    '''Guarantee there is only one value in *iterable* and returns it'''
    val, = iterable # a bit more opaque...
    return val


def all_equal(iterable):
    it = iter(iterable)
    try:
        val = next(it)
    except StopIteration:
        return True
    for item in it:
        if val != item:
            return False
    return True


if __name__ == '__main__':
    assert single('x') == 'x'
    assert single(['hey']) == 'hey'
    assert single(range(1)) == 0
    assert single({'a': 'b'}) == 'a'
    assert single({'c'}) == 'c'
    for fail in [[], '', {'x', 'y', 'z'}, [1, 2, 3], iter([]), range(0), range(int(1e10)), 'hello']:
        try:
            single(fail)
        except ValueError as e:
            pass

    for should_be_true in [[], [1], [2, 2.0], 'aaa', range(0), range(1)]:
        assert all_equal(should_be_true)
    for should_be_false in [[1, 2, 3], 'abc', range(2)]:
        assert not all_equal(should_be_false)
    for should_not_trap in [(x[3] for x in 'something')]:
        try:
            all_equal(should_not_trap)
        except Exception as e:
            pass
        else:
            assert False
