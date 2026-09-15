using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Audio;

public sealed class WaveAlignmentService(WavePcmExtractor? extractor = null)
{
    private readonly WavePcmExtractor _extractor = extractor ?? new WavePcmExtractor();

    public async Task<AlignmentResult> AlignAsync(Stream reference, Stream candidate, SyncMethod method,
        int maximumShiftSamples = 48_000, double threshold = .8, CancellationToken cancellationToken = default)
    {
        ExtractedWaveAudio referenceAudio = await _extractor.ExtractAsync(reference, cancellationToken: cancellationToken).ConfigureAwait(false);
        ExtractedWaveAudio candidateAudio = await _extractor.ExtractAsync(candidate, cancellationToken: cancellationToken).ConfigureAwait(false);
        if (referenceAudio.SampleRate != candidateAudio.SampleRate)
            throw new InvalidDataException("Alignment requires matching sample rates; resampling is not implicit.");
        cancellationToken.ThrowIfCancellationRequested();
        float[] referenceMono = referenceAudio.DownmixToMono();
        float[] candidateMono = candidateAudio.DownmixToMono();
        return method switch
        {
            SyncMethod.Clap or SyncMethod.Transient => PostAlignment.StrongestOnset(referenceMono, candidateMono, method, threshold),
            SyncMethod.WaveformCorrelation => PostAlignment.WaveformCorrelation(referenceMono, candidateMono, maximumShiftSamples, threshold),
            _ => throw new ArgumentException("File alignment supports clap, transient, or waveform correlation.", nameof(method))
        };
    }
}
