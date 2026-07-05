import json

import pytest
import responses
from unittest.mock import Mock, MagicMock

from httpie.compat import is_windows
from httpie.cli.constants import PRETTY_MAP
from httpie.output.streams import BINARY_SUPPRESSED_NOTICE
from httpie.plugins import ConverterPlugin
from httpie.plugins.registry import plugin_manager
from httpie.cli.argparser import HTTPieArgumentParser

from .utils import StdinBytesIO, http, MockEnvironment, DUMMY_URL
from .fixtures import (
    ASCII_FILE_CONTENT,
    BIN_FILE_CONTENT,
    BIN_FILE_PATH,
    FILE_CONTENT as UNICODE_FILE_CONTENT
)

PRETTY_OPTIONS = list(PRETTY_MAP.keys())


class SortJSONConverterPlugin(ConverterPlugin):
    @classmethod
    def supports(cls, mime):
        return mime == 'json/bytes'

    def convert(self, body):
        body = body.lstrip(b'\x00')
        data = json.loads(body)
        return 'application/json', json.dumps(data, sort_keys=True)


# GET because httpbin 500s with binary POST body.


@pytest.mark.skipif(is_windows,
                    reason='Pretty redirect not supported under Windows')
def test_pretty_redirected_stream(httpbin):
    """Test that --stream works with prettified redirected output."""
    env = MockEnvironment(
        colors=256,
        stdin=StdinBytesIO(BIN_FILE_PATH.read_bytes()),
        stdin_isatty=False,
        stdout_isatty=False,
    )
    r = http('--verbose', '--pretty=all', '--stream', 'GET',
             httpbin + '/get', env=env)
    assert BINARY_SUPPRESSED_NOTICE.decode() in r

@pytest.fixture
def mock_env_args():
    """
    Provides an isolated mock instance containing 'args' and 'env' attributes
    to safely test stream hijacking without affecting real system streams.
    """
    instance = MagicMock()
    
    # Mock CLI arguments
    instance.args.output_file = None
    instance.args.download = False
    instance.args.quiet = False
    
    # Mock Environment streams
    instance.env.stdout = MagicMock()
    instance.env.stdout_isatty = True
    instance.env.stderr = MagicMock()
    instance.env.stderr_isatty = True
    instance.env.devnull = MagicMock()
    instance.env.quiet = False
    
    # Mock warning filter
    instance.env.apply_warnings_filter = MagicMock()

    return instance


def test_setup_streams_download_with_pipe(mock_env_args):
    """
    Test that standard streams are correctly redirected when '--download' is used
    and stdout is piped (isatty is False).
    Expected: output_file becomes the original stdout, and stdout is hijacked to stderr.
    """
    # Setup state
    mock_env_args.args.download = True
    mock_env_args.env.stdout_isatty = False  # Simulating piped stdout
    
    original_stdout = mock_env_args.env.stdout
    original_stderr = mock_env_args.env.stderr
    original_stderr_isatty = mock_env_args.env.stderr_isatty

    # Sınıf üzerinden asıl fonksiyonu çağırıyoruz
    HTTPieArgumentParser._setup_standard_streams(mock_env_args)
    
    # Verify stream redirection
    assert mock_env_args.args.output_file == original_stdout, "output_file should be assigned to original stdout"
    assert mock_env_args.env.stdout == original_stderr, "stdout should still be hijacked to stderr"
    assert mock_env_args.env.stdout_isatty == original_stderr_isatty


def test_setup_streams_download_without_pipe(mock_env_args):
    """
    Test stream behavior when '--download' is active but running in a standard TTY.
    Expected: output_file remains untouched, but stdout is still hijacked to stderr.
    """
    mock_env_args.args.download = True
    mock_env_args.env.stdout_isatty = True  # Standard TTY
    
    original_stderr = mock_env_args.env.stderr
    
    # Sınıf üzerinden asıl fonksiyonu çağırıyoruz
    HTTPieArgumentParser._setup_standard_streams(mock_env_args)
    
    assert mock_env_args.args.output_file is None, "output_file should not be modified in TTY mode"
    assert mock_env_args.env.stdout == original_stderr, "stdout should still be hijacked to stderr"


def test_setup_streams_output_file_resets_pointer(mock_env_args):
    """
    Test that standard output files (non-download) are properly truncated
    and the file pointer is reset to 0 before appending new data.
    """
    mock_env_args.args.download = False
    
    # Mock an open file object
    mock_file = MagicMock()
    mock_env_args.args.output_file = mock_file
    
    # Sınıf üzerinden asıl fonksiyonu çağırıyoruz
    HTTPieArgumentParser._setup_standard_streams(mock_env_args)
    
    # Verify file operations
    mock_file.seek.assert_called_once_with(0)

def test_pretty_stream_ensure_full_stream_is_retrieved(httpbin):
    env = MockEnvironment(
        stdin=StdinBytesIO(),
        stdin_isatty=False,
        stdout_isatty=False,
    )
    r = http('--pretty=format', '--stream', 'GET',
             httpbin + '/stream/3', env=env)
    assert r.count('/stream/3') == 3


@pytest.mark.parametrize('pretty', PRETTY_OPTIONS)
@pytest.mark.parametrize('stream', [True, False])
@responses.activate
def test_pretty_options_with_and_without_stream_with_converter(pretty, stream):
    plugin_manager.register(SortJSONConverterPlugin)
    try:
        # Cover PluginManager.__repr__()
        assert 'SortJSONConverterPlugin' in str(plugin_manager)

        body = b'\x00{"foo":42,\n"bar":"baz"}'
        responses.add(responses.GET, DUMMY_URL, body=body,
                      stream=True, content_type='json/bytes')

        args = ['--pretty=' + pretty, 'GET', DUMMY_URL]
        if stream:
            args.insert(0, '--stream')
        r = http(*args)

        assert 'json/bytes' in r
        if pretty == 'none':
            assert BINARY_SUPPRESSED_NOTICE.decode() in r
        else:
            # Ensure the plugin was effectively used and the resulting JSON is sorted
            assert '"bar": "baz",' in r
            assert '"foo": 42' in r
    finally:
        plugin_manager.unregister(SortJSONConverterPlugin)


def test_encoded_stream(httpbin):
    """Test that --stream works with non-prettified
    redirected terminal output."""
    env = MockEnvironment(
        stdin=StdinBytesIO(BIN_FILE_PATH.read_bytes()),
        stdin_isatty=False,
    )
    r = http('--pretty=none', '--stream', '--verbose', 'GET',
             httpbin + '/get', env=env)
    assert BINARY_SUPPRESSED_NOTICE.decode() in r


def test_redirected_stream(httpbin):
    """Test that --stream works with non-prettified
    redirected terminal output."""
    env = MockEnvironment(
        stdout_isatty=False,
        stdin_isatty=False,
        stdin=StdinBytesIO(BIN_FILE_PATH.read_bytes()),
    )
    r = http('--pretty=none', '--stream', '--verbose', 'GET',
             httpbin + '/get', env=env)
    assert BIN_FILE_CONTENT in r


# /drip endpoint produces 3 individual lines,
# if we set text/event-stream HTTPie should stream
# it by default. Otherwise, it will buffer and then
# print.
@pytest.mark.parametrize('extras, expected', [
    (
        ['Accept:text/event-stream'],
        3
    ),
    (
        ['Accept:text/event-stream; charset=utf-8'],
        3
    ),
    (
        ['Accept:text/plain'],
        1
    )
])
def test_auto_streaming(http_server, extras, expected):
    env = MockEnvironment()
    env.stdout.write = Mock()
    http(http_server + '/drip', *extras, env=env)
    assert len([
        call_arg
        for call_arg in env.stdout.write.call_args_list
        if 'test' in call_arg[0][0]
    ]) == expected


def test_streaming_encoding_detection(http_server):
    r = http('--stream', http_server + '/stream/encoding/random')
    assert ASCII_FILE_CONTENT in r
    assert UNICODE_FILE_CONTENT in r
