import os
os.environ['CI_MIN_HOST_INTERVAL']='0'
from ci_engine.collector import assert_public_target, normalize

def expect_error(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError('Expected ValueError')

expect_error(lambda: assert_public_target('http://127.0.0.1/'))
expect_error(lambda: assert_public_target('http://localhost/'))
expect_error(lambda: assert_public_target('http://10.0.0.1/'))
expect_error(lambda: assert_public_target('http://169.254.169.254/latest/meta-data/'))
expect_error(lambda: normalize('https://user:pass@example.com/'))
assert normalize('https://example.com') == 'https://example.com/'
print('collector security tests passed')
