import io
import sys
import wave

from source.pcm import PCM_SAMPLE_BYTES


def decode_wav(recording: bytes) -> tuple[bytes, int]:
    """Return (pcm_s16le, sample_rate) from a stored mono 16-bit WAV."""
    with wave.open(io.BytesIO(recording), 'rb') as stream:
        if stream.getnchannels() != 1 or stream.getsampwidth() != PCM_SAMPLE_BYTES:
            raise ValueError('expected mono 16-bit WAV')
        if stream.getcomptype() != 'NONE':
            raise ValueError('expected uncompressed PCM WAV')
        pcm = stream.readframes(stream.getnframes())
        return pcm, stream.getframerate()


def encode_wav(pcm: bytes, sample_rate: int) -> bytes:
    if not pcm or len(pcm) % PCM_SAMPLE_BYTES:
        raise ValueError('WAV requires nonempty, frame-aligned PCM')
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(PCM_SAMPLE_BYTES)
        output.setframerate(sample_rate)
        if sys.byteorder == 'big':
            # wave.writeframes expects native endianness and writes little endian.
            native = bytearray(pcm)
            native[0::2], native[1::2] = pcm[1::2], pcm[0::2]
            output.writeframes(native)
        else:
            output.writeframes(pcm)
    return stream.getvalue()
