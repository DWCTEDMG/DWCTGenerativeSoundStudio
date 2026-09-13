using System.Collections.Immutable;
using System.Threading.Channels;
using EdmgStudio.Core.Audio;
using Windows.Devices.Enumeration;
using Windows.Media.Audio;
using Windows.Media.Devices;
using Windows.Media.MediaProperties;
using Windows.Storage;

namespace EdmgStudio.WinUI.Services;

public sealed class WindowsAudioEngine : IAudioEngine
{
    private const string DefaultDeviceId = "{default}";
    private readonly Channel<EngineOperation> _operations = Channel.CreateBounded<EngineOperation>(
        new BoundedChannelOptions(128)
        {
            SingleReader = true,
            SingleWriter = false,
            FullMode = BoundedChannelFullMode.Wait
        });
    private readonly Task _worker;
    private DeviceSnapshot _devices = new([]);
    private AudioEngineConfiguration? _configuration;
    private int _disposeState;

    public WindowsAudioEngine()
    {
        _worker = Task.Run(ProcessOperationsAsync);
    }

    public event EventHandler<IReadOnlyList<AudioMeterSnapshot>>? MetersAvailable;

    public IReadOnlyList<AudioDeviceDescriptor> Devices => Volatile.Read(ref _devices).Items;

    public AudioEngineConfiguration? Configuration => Volatile.Read(ref _configuration);

    public async Task RefreshDevicesAsync(CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();
        string selector = MediaDevice.GetAudioRenderSelector();
        DeviceInformationCollection devices;
        try
        {
            devices = await DeviceInformation.FindAllAsync(selector).AsTask(cancellationToken).ConfigureAwait(false);
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            throw new InvalidOperationException(
                "Windows could not enumerate WASAPI render devices. Check Windows audio services and device permissions.",
                exception);
        }

        string defaultId = MediaDevice.GetDefaultAudioRenderId(AudioDeviceRole.Default) ?? string.Empty;
        ImmutableArray<AudioDeviceDescriptor>.Builder results = ImmutableArray.CreateBuilder<AudioDeviceDescriptor>();
        foreach (DeviceInformation device in devices.OrderBy(item => item.Name, StringComparer.CurrentCultureIgnoreCase))
        {
            results.Add(new AudioDeviceDescriptor(
                device.Id,
                string.IsNullOrWhiteSpace(device.Name) ? "Windows audio device" : device.Name,
                AudioDeviceBackend.WasapiShared,
                string.Equals(device.Id, defaultId, StringComparison.OrdinalIgnoreCase),
                []));
        }

        if (results.Count == 0)
        {
            results.Add(new AudioDeviceDescriptor(
                string.IsNullOrWhiteSpace(defaultId) ? DefaultDeviceId : defaultId,
                "Windows default audio device", AudioDeviceBackend.WasapiShared, true, []));
        }

        Volatile.Write(ref _devices, new DeviceSnapshot(results.ToImmutable()));
    }

    public async Task ConfigureAsync(
        AudioEngineConfiguration configuration,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(configuration);
        ThrowIfDisposed();
        _ = new AudioRenderGraph(configuration);
        AudioTrackRoute? unsupportedRoute = configuration.Tracks.FirstOrDefault(
            route => Math.Abs(route.Pan) > float.Epsilon ||
                     !string.Equals(route.OutputBusId, "master", StringComparison.OrdinalIgnoreCase));
        if (unsupportedRoute is not null)
        {
            throw new NotSupportedException(
                $"Track '{unsupportedRoute.TrackId}' uses pan or output-bus routing that WASAPI shared playback does not support yet.");
        }

        PreparedGraph prepared = await PrepareGraphAsync(configuration, cancellationToken).ConfigureAwait(false);
        var completion = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        bool queued = false;
        try
        {
            await _operations.Writer.WriteAsync(
                new EngineOperation(prepared, null, completion), cancellationToken).ConfigureAwait(false);
            queued = true;
            await completion.Task.ConfigureAwait(false);
        }
        catch
        {
            if (!queued)
            {
                prepared.Dispose();
            }
            throw;
        }
    }

    public async ValueTask EnqueueTransportStateAsync(
        TransportState state,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(state);
        ThrowIfDisposed();
        await _operations.Writer.WriteAsync(new EngineOperation(null, state, null), cancellationToken)
            .ConfigureAwait(false);
    }

    public async ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _disposeState, 1) != 0)
        {
            return;
        }

        _operations.Writer.TryComplete();
        await _worker.ConfigureAwait(false);
    }

    private async Task<PreparedGraph> PrepareGraphAsync(
        AudioEngineConfiguration configuration,
        CancellationToken cancellationToken)
    {
        DeviceInformation? selectedDevice = null;
        string deviceId = configuration.DeviceId.Trim();
        if (!string.Equals(deviceId, DefaultDeviceId, StringComparison.OrdinalIgnoreCase))
        {
            try
            {
                selectedDevice = await DeviceInformation.CreateFromIdAsync(deviceId).AsTask(cancellationToken)
                    .ConfigureAwait(false);
            }
            catch (Exception exception) when (exception is not OperationCanceledException)
            {
                throw new InvalidOperationException(
                    $"The selected Windows audio device '{deviceId}' is unavailable.", exception);
            }
        }

        var settings = new AudioGraphSettings(Windows.Media.Render.AudioRenderCategory.Media)
        {
            QuantumSizeSelectionMode = QuantumSizeSelectionMode.ClosestToDesired,
            DesiredSamplesPerQuantum = configuration.BufferFrames,
            EncodingProperties = AudioEncodingProperties.CreatePcm((uint)configuration.SampleRate, 2, 32),
            PrimaryRenderDevice = selectedDevice
        };

        CreateAudioGraphResult graphResult;
        try
        {
            graphResult = await AudioGraph.CreateAsync(settings).AsTask(cancellationToken).ConfigureAwait(false);
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            throw new InvalidOperationException(
                $"Windows could not open the selected WASAPI shared device at {configuration.SampleRate} Hz.",
                exception);
        }

        if (graphResult.Status != AudioGraphCreationStatus.Success || graphResult.Graph is null)
        {
            throw new InvalidOperationException(
                $"Windows could not create the WASAPI shared audio graph (status: {graphResult.Status}).");
        }

        AudioGraph graph = graphResult.Graph;
        var clips = new List<PreparedClip>();
        try
        {
            CreateAudioDeviceOutputNodeResult outputResult = await graph.CreateDeviceOutputNodeAsync()
                .AsTask(cancellationToken).ConfigureAwait(false);
            if (outputResult.Status != AudioDeviceNodeCreationStatus.Success || outputResult.DeviceOutputNode is null)
            {
                throw new InvalidOperationException(
                    $"Windows could not open the WASAPI shared render endpoint (status: {outputResult.Status}).");
            }

            foreach (AudioTrackRoute route in configuration.Tracks)
            {
                if (route.Muted || configuration.Tracks.Any(candidate => candidate.Solo) && !route.Solo)
                {
                    continue;
                }

                foreach (AudioClipSource clip in route.Clips)
                {
                    StorageFile file;
                    try
                    {
                        file = await StorageFile.GetFileFromPathAsync(Path.GetFullPath(clip.SourcePath))
                            .AsTask(cancellationToken).ConfigureAwait(false);
                    }
                    catch (Exception exception) when (exception is not OperationCanceledException)
                    {
                        throw new InvalidOperationException(
                            $"Audio clip '{clip.EventId}' could not open '{clip.SourcePath}'.", exception);
                    }

                    CreateAudioFileInputNodeResult inputResult = await graph.CreateFileInputNodeAsync(file)
                        .AsTask(cancellationToken).ConfigureAwait(false);
                    if (inputResult.Status != AudioFileNodeCreationStatus.Success || inputResult.FileInputNode is null)
                    {
                        throw new InvalidOperationException(
                            $"Audio clip '{clip.EventId}' could not be decoded (status: {inputResult.Status}).");
                    }

                    AudioFileInputNode node = inputResult.FileInputNode;
                    node.OutgoingGain = route.Gain;
                    node.AddOutgoingConnection(outputResult.DeviceOutputNode);
                    node.Stop();
                    clips.Add(new PreparedClip(clip, node));
                }
            }

            return new PreparedGraph(configuration, graph, outputResult.DeviceOutputNode, clips);
        }
        catch
        {
            foreach (PreparedClip clip in clips)
            {
                clip.Node.Dispose();
            }
            graph.Dispose();
            throw;
        }
    }

    private async Task ProcessOperationsAsync()
    {
        PreparedGraph? active = null;
        TransportState? transport = null;
        long transportTimestamp = 0;
        try
        {
            while (await _operations.Reader.WaitToReadAsync().ConfigureAwait(false))
            {
                while (_operations.Reader.TryRead(out EngineOperation operation))
                {
                    try
                    {
                        if (operation.Graph is not null)
                        {
                            operation.Graph.Graph.Start();
                            if (transport is not null)
                            {
                                ApplyTransport(operation.Graph, transport, transportTimestamp);
                            }
                            PreparedGraph? previous = active;
                            active = operation.Graph;
                            Volatile.Write(ref _configuration, active.Configuration);
                            previous?.Dispose();
                            operation.Completion?.TrySetResult();
                        }
                        else if (operation.Transport is not null)
                        {
                            transport = operation.Transport;
                            transportTimestamp = Environment.TickCount64;
                            ApplyTransport(active, transport, transportTimestamp);
                        }
                    }
                    catch (Exception exception)
                    {
                        operation.Graph?.Dispose();
                        operation.Completion?.TrySetException(exception);
                    }
                }

                while (transport?.Mode is TransportMode.Playing or TransportMode.Recording &&
                       Volatile.Read(ref _disposeState) == 0 &&
                       !_operations.Reader.TryPeek(out _))
                {
                    await Task.Delay(10).ConfigureAwait(false);
                    ApplyTransport(active, transport, transportTimestamp);
                }
            }
        }
        catch (Exception exception)
        {
            while (_operations.Reader.TryRead(out EngineOperation pending))
            {
                pending.Completion?.TrySetException(exception);
                pending.Graph?.Dispose();
            }
        }
        finally
        {
            active?.Dispose();
            Volatile.Write(ref _configuration, null);
        }
    }

    private static void ApplyTransport(PreparedGraph? active, TransportState state, long stateTimestamp)
    {
        if (active is null || !string.Equals(active.Configuration.ProjectId, state.ProjectId, StringComparison.Ordinal))
        {
            return;
        }

        long position = ResolvePosition(state, stateTimestamp, Environment.TickCount64);
        bool running = state.Mode is TransportMode.Playing or TransportMode.Recording;
        foreach (PreparedClip clip in active.Clips)
        {
            bool shouldPlay = running && position >= clip.Source.TimelineStartSample &&
                              position < clip.Source.TimelineEndSample;
            if (!shouldPlay)
            {
                if (clip.IsPlaying)
                {
                    clip.Node.Stop();
                    clip.IsPlaying = false;
                }
                continue;
            }

            long projectOffset = position - clip.Source.TimelineStartSample;
            long sourceSample = clip.Source.SourceStartSample +
                                projectOffset * clip.Source.SourceSampleRate / active.Configuration.SampleRate;
            TimeSpan sourcePosition = TimeSpan.FromSeconds(sourceSample / (double)clip.Source.SourceSampleRate);
            if (!clip.IsPlaying || Math.Abs((clip.Node.Position - sourcePosition).TotalMilliseconds) > 100)
            {
                clip.Node.Seek(sourcePosition);
            }
            if (!clip.IsPlaying)
            {
                clip.Node.Start();
                clip.IsPlaying = true;
            }
        }
    }

    internal static long ResolvePosition(TransportState state, long stateTimestamp, long currentTimestamp)
    {
        if (state.Mode == TransportMode.Stopped)
        {
            return state.PositionSamples;
        }

        long elapsedMilliseconds = Math.Max(0, currentTimestamp - stateTimestamp);
        long position = state.PositionSamples + elapsedMilliseconds * state.SampleRate / 1000;
        if (state.Loop.Enabled && position >= state.Loop.EndSample)
        {
            long length = state.Loop.EndSample - state.Loop.StartSample;
            return state.Loop.StartSample + (position - state.Loop.StartSample) % length;
        }
        return Math.Min(position, state.DurationSamples);
    }

    private void ThrowIfDisposed()
    {
        ObjectDisposedException.ThrowIf(Volatile.Read(ref _disposeState) != 0, this);
    }

    private sealed record DeviceSnapshot(ImmutableArray<AudioDeviceDescriptor> Items);

    private readonly record struct EngineOperation(
        PreparedGraph? Graph,
        TransportState? Transport,
        TaskCompletionSource? Completion);

    private sealed class PreparedGraph : IDisposable
    {
        public PreparedGraph(
            AudioEngineConfiguration configuration,
            AudioGraph graph,
            AudioDeviceOutputNode output,
            List<PreparedClip> clips)
        {
            Configuration = configuration;
            Graph = graph;
            Output = output;
            Clips = clips;
        }

        public AudioEngineConfiguration Configuration { get; }
        public AudioGraph Graph { get; }
        public AudioDeviceOutputNode Output { get; }
        public List<PreparedClip> Clips { get; }

        public void Dispose()
        {
            Graph.Stop();
            foreach (PreparedClip clip in Clips)
            {
                clip.Node.Dispose();
            }
            Output.Dispose();
            Graph.Dispose();
        }
    }

    private sealed class PreparedClip(AudioClipSource source, AudioFileInputNode node)
    {
        public AudioClipSource Source { get; } = source;
        public AudioFileInputNode Node { get; } = node;
        public bool IsPlaying { get; set; }
    }
}
