using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Audio;

public sealed class WaveAlignmentService(WavePcmExtractor? extractor = null)
{
    public const int MaximumSamplesPerSource = 2_880_000;
    public const int MaximumShiftSamples = 480_000;
    public const long MaximumCorrelationOperations = 250_000_000;

    private readonly WavePcmExtractor _extractor = extractor ?? new WavePcmExtractor();

    public async Task<AlignmentResult> AlignAsync(Stream reference, Stream candidate, SyncMethod method,
        int maximumShiftSamples = 48_000, double threshold = .8, CancellationToken cancellationToken = default,
        int? requiredSampleRate = null)
    {
        if (maximumShiftSamples < 0 || maximumShiftSamples > MaximumShiftSamples)
            throw new ArgumentOutOfRangeException(nameof(maximumShiftSamples), $"Maximum shift cannot exceed {MaximumShiftSamples} samples.");

        ExtractedWaveAudio referenceAudio = await _extractor.ExtractAsync(reference, cancellationToken: cancellationToken).ConfigureAwait(false);
        ExtractedWaveAudio candidateAudio = await _extractor.ExtractAsync(candidate, cancellationToken: cancellationToken).ConfigureAwait(false);
        if (referenceAudio.SampleRate != candidateAudio.SampleRate)
            throw new InvalidDataException("Alignment requires matching source sample rates; resampling is not implicit.");
        if (requiredSampleRate is > 0 && referenceAudio.SampleRate != requiredSampleRate)
            throw new InvalidDataException($"Alignment source rate {referenceAudio.SampleRate} Hz does not match the project rate {requiredSampleRate} Hz.");
        if (referenceAudio.FrameCount > MaximumSamplesPerSource || candidateAudio.FrameCount > MaximumSamplesPerSource)
            throw new InvalidDataException($"Alignment sources are limited to {MaximumSamplesPerSource} sample frames each.");

        float[] referenceMono = referenceAudio.DownmixToMono(cancellationToken);
        float[] candidateMono = candidateAudio.DownmixToMono(cancellationToken);
        return method switch
        {
            SyncMethod.Clap or SyncMethod.Transient => PostAlignment.StrongestOnset(referenceMono, candidateMono, method, threshold, cancellationToken),
            SyncMethod.WaveformCorrelation => BoundedCorrelation(referenceMono, candidateMono, maximumShiftSamples, threshold, cancellationToken),
            _ => throw new ArgumentException("File alignment supports clap, transient, or waveform correlation.", nameof(method))
        };
    }

    private static AlignmentResult BoundedCorrelation(float[] reference, float[] candidate, int maximumShiftSamples,
        double threshold, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        CorrelationPlan plan = PlanCorrelation(reference.Length, candidate.Length, maximumShiftSamples);
        if (plan.DownsampleFactor == 1)
            return PostAlignment.WaveformCorrelation(reference, candidate, plan.EffectiveMaximumShift, threshold,
                cancellationToken, MaximumCorrelationOperations);

        float[] coarseReference = Downsample(reference, plan.DownsampleFactor, cancellationToken);
        float[] coarseCandidate = Downsample(candidate, plan.DownsampleFactor, cancellationToken);
        AlignmentResult coarse = PostAlignment.WaveformCorrelation(coarseReference, coarseCandidate,
            plan.CoarseMaximumShift, 0, cancellationToken, plan.CoarseOperations);

        int center = Math.Clamp(checked((int)coarse.OffsetSamples * plan.DownsampleFactor),
            -plan.EffectiveMaximumShift, plan.EffectiveMaximumShift);
        ReadOnlySpan<float> adjustedReference = reference;
        ReadOnlySpan<float> adjustedCandidate = candidate;
        if (center >= 0)
            adjustedCandidate = candidate.AsSpan(Math.Min(center, candidate.Length));
        else
            adjustedReference = reference.AsSpan(Math.Min(-center, reference.Length));
        int localLimit = Math.Min(plan.RefinementRadius,
            Math.Min(adjustedReference.Length, adjustedCandidate.Length) - 3);
        if (localLimit < 0)
            return coarse with { OffsetSamples = center, Diagnostics = $"Bounded coarse correlation; resolution ±{plan.DownsampleFactor} samples." };

        long remainingBudget = MaximumCorrelationOperations - plan.CoarseOperations;
        int refinementLength = (int)Math.Min(
            Math.Min(adjustedReference.Length, adjustedCandidate.Length),
            remainingBudget / (2L * (2L * localLimit + 1L)));
        if (refinementLength < 3)
            return coarse with { OffsetSamples = center, Diagnostics = $"Bounded coarse correlation; resolution ±{plan.DownsampleFactor} samples." };
        adjustedReference = adjustedReference[..refinementLength];
        adjustedCandidate = adjustedCandidate[..refinementLength];
        AlignmentResult refined = PostAlignment.WaveformCorrelation(adjustedReference, adjustedCandidate, localLimit,
            threshold, cancellationToken, remainingBudget);
        long offset = Math.Clamp(center + refined.OffsetSamples, -plan.EffectiveMaximumShift, plan.EffectiveMaximumShift);
        return refined with
        {
            OffsetSamples = offset,
            Diagnostics = refined.Diagnostics + $" Deterministic budgeted coarse-to-fine search used 1:{plan.DownsampleFactor} analysis and a {refinementLength:N0}-sample refinement window."
        };
    }

    internal static CorrelationPlan PlanCorrelation(int referenceLength, int candidateLength, int maximumShiftSamples)
    {
        if (referenceLength < 3 || candidateLength < 3) return new(1, 0, 0, 0, 0);
        int minimumLength = Math.Min(referenceLength, candidateLength);
        int minimumOverlap = Math.Min(4096, Math.Max(3, minimumLength / 4));
        int effectiveMaximumShift = Math.Min(maximumShiftSamples, Math.Max(0, minimumLength - minimumOverlap));
        for (int factor = 1; factor <= Math.Max(1, minimumLength / 3); factor++)
        {
            int coarseReferenceLength = (referenceLength + factor - 1) / factor;
            int coarseCandidateLength = (candidateLength + factor - 1) / factor;
            int coarseShift = (effectiveMaximumShift + factor - 1) / factor;
            long coarseWork = CorrelationWork(coarseReferenceLength, coarseCandidateLength, coarseShift);
            if (factor == 1 && coarseWork <= MaximumCorrelationOperations)
                return new(1, effectiveMaximumShift, coarseShift, 0, coarseWork);
            int radius = Math.Min(effectiveMaximumShift, factor * 2);
            long minimumRefinementWork = CorrelationWork(4096, 4096, radius);
            if (coarseWork < MaximumCorrelationOperations
                && minimumRefinementWork <= MaximumCorrelationOperations - coarseWork)
                return new(factor, effectiveMaximumShift, coarseShift, radius, coarseWork);
        }
        throw new InvalidOperationException("The requested source and shift limits cannot be analyzed within the correlation budget.");
    }

    internal readonly record struct CorrelationPlan(int DownsampleFactor, int EffectiveMaximumShift,
        int CoarseMaximumShift, int RefinementRadius, long CoarseOperations);

    private static float[] Downsample(ReadOnlySpan<float> samples, int factor, CancellationToken cancellationToken)
    {
        float[] result = new float[(samples.Length + factor - 1) / factor];
        for (int output = 0; output < result.Length; output++)
        {
            if ((output & 0x3ff) == 0) cancellationToken.ThrowIfCancellationRequested();
            int start = output * factor;
            int end = Math.Min(samples.Length, start + factor);
            double sum = 0;
            for (int index = start; index < end; index++) sum += samples[index];
            result[output] = (float)(sum / (end - start));
        }
        return result;
    }

    private static long CorrelationWork(int referenceLength, int candidateLength, int maximumShiftSamples)
    {
        try { return checked((2L * maximumShiftSamples + 1) * Math.Min(referenceLength, candidateLength) * 2); }
        catch (OverflowException) { return long.MaxValue; }
    }
}
