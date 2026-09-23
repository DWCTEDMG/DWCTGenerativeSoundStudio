using EdmgStudio.Core.Audio;
using System.Collections.Immutable;
using System.Runtime.InteropServices;
using System.Threading.Channels;
using Windows.Devices.Enumeration;
using Windows.Foundation;
using Windows.Media;
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
  private readonly Func<long> _timestamp;
  private readonly IVst3HostSession _vst3Host;
  private Exception? _failure;
  private DeviceSnapshot _devices = new([]);
  private AudioEngineConfiguration? _configuration;
  private int _disposeState;

  public WindowsAudioEngine() : this(new UnavailableVst3HostSession(), () => Environment.TickCount64)
  {
  }

  public WindowsAudioEngine(IVst3HostSession vst3Host) : this(vst3Host, () => Environment.TickCount64)
  {
  }

  internal WindowsAudioEngine(Func<long> timestamp) : this(new UnavailableVst3HostSession(), timestamp)
  {
  }

  internal WindowsAudioEngine(IVst3HostSession vst3Host, Func<long> timestamp)
  {
    _vst3Host = vst3Host ?? throw new ArgumentNullException(nameof(vst3Host));
    _timestamp = timestamp;
    WorkerCompletion = Task.Run(ProcessOperationsAsync);
  }

  internal Task WorkerCompletion { get; }

public event EventHandler<IReadOnlyList<AudioMeterSnapshot>>? MetersAvailable;

public IReadOnlyList<AudioDeviceDescriptor> Devices => Volatile.Read(ref _devices).Items;

  public AudioEngineConfiguration? Configuration => Volatile.Read(ref _configuration);
  public string? FailureMessage => Volatile.Read(ref _failure) is null ? null :
      "Audio playback stopped after an engine failure. Restart Studio to reopen the audio device.";
  public string MixerProcessingCapability =>
      "AudioGraph captures decoded per-track float quanta, executes the Core mixer with ordered isolated VST3 inserts, sends and PDC, then submits the processed stereo master to WASAPI shared output.";

  internal static MixerProcessor CreateCoreProcessor(AudioEngineConfiguration configuration,
      IEnumerable<MixerInsertBinding>? insertBindings = null,
      int? maximumFrames = null)
  {
    MixerGraphPlan plan = configuration.MixerChannels.IsDefaultOrEmpty
        ? MixerGraphBuilder.FromAudioRoutes(configuration)
        : MixerGraphBuilder.Build(configuration.MixerChannels);
    return new MixerProcessor(plan, maximumFrames ?? configuration.BufferFrames, insertBindings);
  }

  internal static bool IsProcessorCompatible(IVst3InsertProcessor processor, MixerInsert insert,
      int sampleRate, int requiredFrames) =>
      !string.IsNullOrWhiteSpace(insert.ModulePath) &&
      !string.IsNullOrWhiteSpace(insert.PluginId) &&
      string.Equals(Path.GetFullPath(processor.ModulePath), Path.GetFullPath(insert.ModulePath), StringComparison.OrdinalIgnoreCase) &&
      string.Equals(processor.PluginId, insert.PluginId, StringComparison.OrdinalIgnoreCase) &&
      processor.SampleRate == sampleRate &&
      processor.MaximumFrames >= requiredFrames;

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
    if (Volatile.Read(ref _failure) is Exception failure)
    {
      throw new InvalidOperationException(FailureMessage, failure);
    }
    _ = new AudioRenderGraph(configuration);
    _ = configuration.MixerChannels.IsDefaultOrEmpty
        ? MixerGraphBuilder.FromAudioRoutes(configuration)
        : MixerGraphBuilder.Build(configuration.MixerChannels);

    PreparedGraph prepared = await PrepareGraphAsync(configuration, cancellationToken).ConfigureAwait(false);
    TaskCompletionSource completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
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

    _ = _operations.Writer.TryComplete();
    await WorkerCompletion.ConfigureAwait(false);
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

    AudioGraphSettings settings = CreateGraphSettings(configuration, selectedDevice);

    CreateAudioGraphResult graphResult = default!;
    try
    {
      graphResult = await AudioGraph.CreateAsync(settings).AsTask(cancellationToken).ConfigureAwait(false);
    }
    catch (Exception exception) when (exception is not OperationCanceledException)
    {
      // Diagnostic + fallback: if a specific device was requested, try the system default device,
      // then finally try creating the graph without a PrimaryRenderDevice so AudioGraph picks the best match.
      System.Diagnostics.Trace.TraceWarning($"AudioGraph.CreateAsync failed for device '{selectedDevice?.Id ?? "<none>"}': {exception.Message}. Attempting fallback to default device and then to automatic selection.");
      if (selectedDevice is not null)
      {
        try
        {
          string defaultId = MediaDevice.GetDefaultAudioRenderId(AudioDeviceRole.Default) ?? string.Empty;
          DeviceInformation? defaultDevice = null;
          if (!string.IsNullOrWhiteSpace(defaultId))
          {
            try { defaultDevice = await DeviceInformation.CreateFromIdAsync(defaultId).AsTask(cancellationToken).ConfigureAwait(false); } catch { defaultDevice = null; }
          }

          graphResult = await AudioGraph.CreateAsync(CreateGraphSettings(configuration, defaultDevice)).AsTask(cancellationToken).ConfigureAwait(false);
        }
        catch (Exception) when (exception is not OperationCanceledException)
        {
          try
          {
            graphResult = await AudioGraph.CreateAsync(CreateGraphSettings(configuration, null)).AsTask(cancellationToken).ConfigureAwait(false);
          }
          catch (Exception ex3) when (ex3 is not OperationCanceledException)
          {
            throw new InvalidOperationException(
              "Windows could not open the selected WASAPI shared device using its configured format (primary and fallback attempts failed).",
              ex3);
          }
        }
      }
      else
      {
        throw new InvalidOperationException(
            "Windows could not open the selected WASAPI shared device using its configured format.",
            exception);
      }
    }

    if (graphResult.Status != AudioGraphCreationStatus.Success || graphResult.Graph is null)
    {
      throw new InvalidOperationException(
          $"Windows could not create the WASAPI shared audio graph using the device format (status: {graphResult.Status}).");
    }

    AudioGraph graph = graphResult.Graph;
    List<PreparedClip> clips = new();
    List<PreparedTrack> tracks = new();
    AudioFrameInputNode? masterInput = null;
    try
    {
      CreateAudioDeviceOutputNodeResult outputResult = await graph.CreateDeviceOutputNodeAsync()
          .AsTask(cancellationToken).ConfigureAwait(false);
      if (outputResult.Status != AudioDeviceNodeCreationStatus.Success || outputResult.DeviceOutputNode is null)
      {
        System.Diagnostics.Trace.TraceWarning($"CreateDeviceOutputNodeAsync failed with status {outputResult.Status}. Attempting a graph recreate with no PrimaryRenderDevice as a fallback.");
        // Try a single recreate with no PrimaryRenderDevice to let AudioGraph pick a compatible device/format.
        graph.Dispose();
        CreateAudioGraphResult fallbackGraphResult = await AudioGraph.CreateAsync(CreateGraphSettings(configuration, null)).AsTask(cancellationToken).ConfigureAwait(false);
        if (fallbackGraphResult.Status != AudioGraphCreationStatus.Success || fallbackGraphResult.Graph is null)
        {
          throw new InvalidOperationException(
            $"Windows could not create the WASAPI shared audio output node (initial status: {outputResult.Status}, fallback graph status: {fallbackGraphResult.Status}).");
        }
        graph = fallbackGraphResult.Graph;
        outputResult = await graph.CreateDeviceOutputNodeAsync().AsTask(cancellationToken).ConfigureAwait(false);
        if (outputResult.Status != AudioDeviceNodeCreationStatus.Success || outputResult.DeviceOutputNode is null)
        {
          graph.Dispose();
          throw new InvalidOperationException(
            $"Windows could not open the WASAPI shared render endpoint after fallback (status: {outputResult.Status}).");
        }
      }

      int graphQuantumFrames = checked((int)graph.SamplesPerQuantum);
      if (graphQuantumFrames <= 0)
        throw new InvalidOperationException("Windows reported an invalid AudioGraph quantum size.");
      AudioEncodingProperties floatStereo = AudioEncodingProperties.CreatePcm(
          (uint)configuration.SampleRate, 2, 32);
      floatStereo.Subtype = MediaEncodingSubtypes.Float;
      masterInput = graph.CreateFrameInputNode(floatStereo);
      masterInput.AddOutgoingConnection(outputResult.DeviceOutputNode);
      masterInput.Stop();

      foreach (AudioTrackRoute route in configuration.Tracks)
      {
        AudioFrameOutputNode trackOutput = graph.CreateFrameOutputNode(floatStereo);
        trackOutput.Stop();
        var preparedTrack = new PreparedTrack(route.TrackId, trackOutput,
            new float[checked(graphQuantumFrames * 2)]);
        tracks.Add(preparedTrack);

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
          node.OutgoingGain = 1;
          node.AddOutgoingConnection(trackOutput);
          node.Stop();
          clips.Add(new PreparedClip(clip, node));
        }
      }

      List<MixerInsertBinding> bindings = new();
      if (!configuration.MixerChannels.IsDefaultOrEmpty)
      {
        foreach (MixerChannel channel in configuration.MixerChannels)
          foreach (MixerInsert insert in channel.Inserts.Where(item => item.Enabled))
          {
            if (insert.Bypassed) continue;
            bool foundProcessor = _vst3Host.TryGetProcessor(insert.Id, out IVst3InsertProcessor? processor) && processor is not null;
            if (foundProcessor && !IsProcessorCompatible(processor!, insert, configuration.SampleRate, graphQuantumFrames))
            {
              await _vst3Host.RemoveInstanceAsync(insert.Id, cancellationToken).ConfigureAwait(false);
              processor = null;
              foundProcessor = false;
            }
            if (!foundProcessor)
            {
              if (string.IsNullOrWhiteSpace(insert.PluginId) || string.IsNullOrWhiteSpace(insert.ModulePath) || string.IsNullOrWhiteSpace(insert.ModuleSha256))
                throw new InvalidOperationException($"Enabled VST3 insert '{insert.Id}' has no verified module identity.");
              Vst3ModuleFingerprint fingerprint = await Vst3ModuleFingerprinting.CreateAsync(insert.ModulePath, cancellationToken).ConfigureAwait(false);
              if (!string.Equals(fingerprint.Sha256, insert.ModuleSha256, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException($"VST3 module for insert '{insert.Id}' changed after discovery. Rescan it before playback.");
              Vst3InstanceStatus status = await _vst3Host.CreateInstanceAsync(new(
                  insert.Id, insert.ModulePath, insert.PluginId, configuration.SampleRate, graphQuantumFrames), cancellationToken).ConfigureAwait(false);
              if (!status.Active)
                throw new InvalidOperationException(status.Diagnostic ?? $"VST3 insert '{insert.Id}' did not become active.");
              if (!string.IsNullOrWhiteSpace(insert.StateBase64))
              {
                byte[] state;
                try { state = Convert.FromBase64String(insert.StateBase64); }
                catch (FormatException exception) { throw new InvalidDataException($"VST3 state for insert '{insert.Id}' is malformed.", exception); }
                status = await _vst3Host.SetStateAsync(insert.Id, state, cancellationToken).ConfigureAwait(false);
                if (!status.Active) throw new InvalidOperationException(status.Diagnostic ?? $"VST3 state for insert '{insert.Id}' could not be restored.");
              }
              if (!_vst3Host.TryGetProcessor(insert.Id, out processor) || processor is null)
                throw new InvalidOperationException($"VST3 insert '{insert.Id}' has no active audio processor after startup.");
            }
            bindings.Add(new MixerInsertBinding(channel.Id, insert.Id, processor!));
          }
      }

      var prepared = new PreparedGraph(configuration, graph, outputResult.DeviceOutputNode,
          masterInput, tracks, clips, CreateCoreProcessor(configuration, bindings, graphQuantumFrames),
          graphQuantumFrames, this);
      masterInput.QuantumStarted += prepared.OnQuantumStarted;
      return prepared;
    }
    catch
    {
      foreach (PreparedClip clip in clips) clip.Node.Dispose();
      foreach (PreparedTrack track in tracks) track.Output.Dispose();
      masterInput?.Dispose();
      graph.Dispose();
      throw;
    }
  }

  internal static AudioGraphSettings CreateGraphSettings(
      AudioEngineConfiguration configuration,
      DeviceInformation? selectedDevice)
  {
    return new AudioGraphSettings(Windows.Media.Render.AudioRenderCategory.Media)
    {
      QuantumSizeSelectionMode = QuantumSizeSelectionMode.ClosestToDesired,
      DesiredSamplesPerQuantum = configuration.BufferFrames,
      PrimaryRenderDevice = selectedDevice
    };
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
              DisposeGraph(previous);
              _ = (operation.Completion?.TrySetResult());
            }
            else if (operation.Transport is not null)
            {
              transport = operation.Transport;
              transportTimestamp = _timestamp();
              ApplyTransport(active, transport, transportTimestamp, transportChanged: true);
            }
          }
          catch (Exception exception)
          {
            _ = (operation.Completion?.TrySetException(exception));
            DisposeGraph(operation.Graph);
            if (operation.Completion is null)
            {
              throw;
            }
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
      Volatile.Write(ref _failure, exception);
      // Close before draining so concurrent/future producers cannot enqueue into a dead worker.
      _ = _operations.Writer.TryComplete(exception);
      while (_operations.Reader.TryRead(out EngineOperation pending))
      {
        _ = (pending.Completion?.TrySetException(exception));
        DisposeGraph(pending.Graph);
      }
    }
    finally
    {
      _ = _operations.Writer.TryComplete();
      DisposeGraph(active);
      Volatile.Write(ref _configuration, null);
    }
  }

  private static void DisposeGraph(PreparedGraph? graph)
  {
    try
    {
      graph?.Dispose();
    }
    catch (Exception exception)
    {
      System.Diagnostics.Trace.TraceError($"Audio graph cleanup failed: {exception}");
    }
  }

  private void ApplyTransport(PreparedGraph? active, TransportState state, long stateTimestamp,
      bool transportChanged = false)
  {
    if (active is null || !string.Equals(active.Configuration.ProjectId, state.ProjectId, StringComparison.Ordinal))
    {
      return;
    }

     AudioPlaybackPosition playback = active.Cursor.Advance(
        state, stateTimestamp, _timestamp(), transportChanged);
    long position = playback.Samples;
    bool running = state.Mode is TransportMode.Playing or TransportMode.Recording;
    if (playback.RequiresSeek || transportChanged) active.SetSamplePosition(position);
    if (running)
    {
      active.MasterInput.Start();
      foreach (PreparedTrack track in active.Tracks) track.Output.Start();
    }
    else
    {
      active.MasterInput.Stop();
      foreach (PreparedTrack track in active.Tracks) track.Output.Stop();
    }
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
      if (playback.RequiresSeek || !clip.IsPlaying || Math.Abs((clip.Node.Position - sourcePosition).TotalMilliseconds) > 100)
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
    private readonly WindowsAudioEngine _owner;
    private readonly MixerProcessor _mixer;
    private readonly MixerInputBlock[] _inputs;
    private readonly float[] _output;
    private readonly MixerMeterSnapshot[] _meterBuffer;
    private readonly AudioAutomationSnapshot _automation;
    private long _samplePosition;
    private int _disposed;

    public PreparedGraph(
        AudioEngineConfiguration configuration,
        AudioGraph graph,
        AudioDeviceOutputNode output,
        AudioFrameInputNode masterInput,
        List<PreparedTrack> tracks,
        List<PreparedClip> clips,
        MixerProcessor mixer,
        int maximumFrames,
        WindowsAudioEngine owner)
    {
      Configuration = configuration;
      Graph = graph;
      Output = output;
      MasterInput = masterInput;
      Tracks = tracks;
      Clips = clips;
      _mixer = mixer;
      _owner = owner;
      _inputs = tracks.Select(track => new MixerInputBlock(track.ChannelId, track.Buffer)).ToArray();
      _output = new float[checked(maximumFrames * 2)];
      _meterBuffer = new MixerMeterSnapshot[mixer.ChannelIds.Length];
      _automation = configuration.Automation ?? AudioAutomationSnapshot.Empty;
    }

    public AudioEngineConfiguration Configuration { get; }
    public AudioPlaybackCursor Cursor { get; } = new();
    public AudioGraph Graph { get; }
    public AudioDeviceOutputNode Output { get; }
    public AudioFrameInputNode MasterInput { get; }
    public List<PreparedTrack> Tracks { get; }
    public List<PreparedClip> Clips { get; }

    public void OnQuantumStarted(AudioFrameInputNode sender, FrameInputNodeQuantumStartedEventArgs args)
    {
      int frames = args.RequiredSamples;
      if (frames <= 0 || Volatile.Read(ref _disposed) != 0) return;
      if (frames > _mixer.MaximumFrames)
        throw new InvalidOperationException($"AudioGraph requested {frames} frames, exceeding the negotiated capacity {_mixer.MaximumFrames}.");
      int sampleCount = checked(frames * 2);
      try
      {
        foreach (PreparedTrack track in Tracks)
        {
          Array.Clear(track.Buffer, 0, sampleCount);
          using AudioFrame frame = track.Output.GetFrame();
          CopyFrameToStereo(frame, track.Buffer, sampleCount);
        }

        _mixer.ProcessBlock(_inputs, _output, frames, Math.Max(0, _samplePosition), _automation);
        var outputFrame = new AudioFrame((uint)(sampleCount * sizeof(float)));
        CopyStereoToFrame(_output, outputFrame, sampleCount);
        sender.AddFrame(outputFrame);

        int meterCount = _mixer.CopyMeterSnapshots(_meterBuffer);
        if (_owner.MetersAvailable is EventHandler<IReadOnlyList<AudioMeterSnapshot>> handler)
        {
          var snapshots = new AudioMeterSnapshot[meterCount];
          for (int index = 0; index < meterCount; index++)
          {
            MixerMeterSnapshot meter = _meterBuffer[index];
            snapshots[index] = new AudioMeterSnapshot(meter.ChannelId, meter.PeakLeft, meter.PeakRight,
                meter.RmsLeft, meter.RmsRight, _samplePosition);
          }
          handler(_owner, snapshots);
        }
        _samplePosition = checked(_samplePosition + frames);
      }
      catch (Exception exception)
      {
        System.Diagnostics.Trace.TraceError($"Audio mixer quantum failed: {exception}");
        sender.AddFrame(new AudioFrame((uint)(sampleCount * sizeof(float))));
      }
    }

    public void SetSamplePosition(long samplePosition)
    {
      _samplePosition = Math.Max(0, samplePosition);
    }

    public void Dispose()
    {
      if (Interlocked.Exchange(ref _disposed, 1) != 0) return;
      List<Exception>? failures = null;
      void Release(Action action)
      {
        try { action(); }
        catch (Exception exception) { (failures ??= []).Add(exception); }
      }
      Release(Graph.Stop);
      MasterInput.QuantumStarted -= OnQuantumStarted;
      foreach (PreparedClip clip in Clips) Release(clip.Node.Dispose);
      foreach (PreparedTrack track in Tracks) Release(track.Output.Dispose);
      Release(MasterInput.Dispose);
      Release(Output.Dispose);
      Release(Graph.Dispose);
      if (failures is not null)
        throw new AggregateException("Audio graph resources could not all be released cleanly.", failures);
    }
  }

  private static unsafe void CopyFrameToStereo(AudioFrame frame, float[] destination, int sampleCount)
  {
    using AudioBuffer buffer = frame.LockBuffer(AudioBufferAccessMode.Read);
    using IMemoryBufferReference reference = buffer.CreateReference();
    ((IMemoryBufferByteAccess)reference).GetBuffer(out byte* bytes, out uint capacity);
    int available = Math.Min(sampleCount, checked((int)capacity / sizeof(float)));
    new ReadOnlySpan<float>(bytes, available).CopyTo(destination);
  }

  private static unsafe void CopyStereoToFrame(float[] source, AudioFrame frame, int sampleCount)
  {
    using AudioBuffer buffer = frame.LockBuffer(AudioBufferAccessMode.Write);
    using IMemoryBufferReference reference = buffer.CreateReference();
    ((IMemoryBufferByteAccess)reference).GetBuffer(out byte* bytes, out uint capacity);
    int available = Math.Min(sampleCount, checked((int)capacity / sizeof(float)));
    source.AsSpan(0, available).CopyTo(new Span<float>(bytes, available));
  }

  [ComImport]
  [Guid("5B0D3235-4DBA-4D44-8659-1BCAD79B9C4F")]
  [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  private unsafe interface IMemoryBufferByteAccess
  {
    void GetBuffer(out byte* buffer, out uint capacity);
  }

  private sealed class PreparedTrack(string channelId, AudioFrameOutputNode output, float[] buffer)
  {
    public string ChannelId { get; } = channelId;
    public AudioFrameOutputNode Output { get; } = output;
    public float[] Buffer { get; } = buffer;
  }

  private sealed class PreparedClip(AudioClipSource source, AudioFileInputNode node)
  {
    public AudioClipSource Source { get; } = source;
    public AudioFileInputNode Node { get; } = node;
    public bool IsPlaying { get; set; }
  }
}
