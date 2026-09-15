using System.Collections.Immutable;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace EdmgStudio.Core.RemoteControl;

public static class StudioCommandIds
{
    public const string TransportPlayPause = "transport.play-pause";
    public const string TransportStop = "transport.stop";
    public const string TransportStepBackward = "transport.step-backward";
    public const string TransportStepForward = "transport.step-forward";
    public const string MixerSelectedGain = "mixer.selected.gain";
    public const string MixerSelectedPan = "mixer.selected.pan";
    public const string MixerSelectedMute = "mixer.selected.mute";
    public const string MixerSelectedSolo = "mixer.selected.solo";
}

public sealed record StudioCommandDescriptor(string Id, string Name, string Category, bool AcceptsContinuousValue);

public static class StudioCommandRegistry
{
    public static ImmutableArray<StudioCommandDescriptor> Commands { get; } =
    [
        new(StudioCommandIds.TransportPlayPause, "Play / pause", "Transport", false),
        new(StudioCommandIds.TransportStop, "Stop and return to start", "Transport", false),
        new(StudioCommandIds.TransportStepBackward, "Step backward one frame", "Transport", false),
        new(StudioCommandIds.TransportStepForward, "Step forward one frame", "Transport", false),
        new(StudioCommandIds.MixerSelectedGain, "Selected channel gain", "Mixer", true),
        new(StudioCommandIds.MixerSelectedPan, "Selected channel pan", "Mixer", true),
        new(StudioCommandIds.MixerSelectedMute, "Toggle selected channel mute", "Mixer", false),
        new(StudioCommandIds.MixerSelectedSolo, "Toggle selected channel solo", "Mixer", false),
    ];

    private static readonly IReadOnlyDictionary<string, StudioCommandDescriptor> ById =
        Commands.ToDictionary(command => command.Id, StringComparer.Ordinal);

    public static bool TryGet(string id, out StudioCommandDescriptor? command) => ById.TryGetValue(id, out command);
}

public sealed record StudioCommandInvocation(string CommandId, string Source, double? NormalizedValue = null);
public sealed record StudioCommandState(bool IsAvailable, string? UnavailableReason = null, string? DisplayValue = null);
public sealed record StudioCommandResult(bool Executed, string? Message = null);

public interface IStudioCommandDispatcher
{
    event EventHandler? StateChanged;
    IDisposable Register(string commandId, Func<StudioCommandInvocation, ValueTask<StudioCommandResult>> handler,
        Func<StudioCommandState>? state = null);
    StudioCommandState GetState(string commandId);
    ValueTask<StudioCommandResult> DispatchAsync(StudioCommandInvocation invocation);
    void NotifyStateChanged();
}

public sealed class StudioCommandDispatcher : IStudioCommandDispatcher
{
    private readonly object _sync = new();
    private readonly Dictionary<string, Registration> _handlers = new(StringComparer.Ordinal);

    public event EventHandler? StateChanged;

    public IDisposable Register(string commandId, Func<StudioCommandInvocation, ValueTask<StudioCommandResult>> handler,
        Func<StudioCommandState>? state = null)
    {
        if (!StudioCommandRegistry.TryGet(commandId, out _)) throw new ArgumentException($"Unknown Studio command '{commandId}'.", nameof(commandId));
        ArgumentNullException.ThrowIfNull(handler);
        var registration = new Registration(this, commandId, handler, state);
        lock (_sync)
        {
            if (!_handlers.TryAdd(commandId, registration)) throw new InvalidOperationException($"Studio command '{commandId}' already has an active handler.");
        }
        StateChanged?.Invoke(this, EventArgs.Empty);
        return registration;
    }

    public StudioCommandState GetState(string commandId)
    {
        Registration? registration;
        lock (_sync) _handlers.TryGetValue(commandId, out registration);
        return registration is null
            ? new(false, "The command is not available in the current workspace.")
            : registration.State?.Invoke() ?? new(true);
    }

    public ValueTask<StudioCommandResult> DispatchAsync(StudioCommandInvocation invocation)
    {
        ArgumentNullException.ThrowIfNull(invocation);
        if (!StudioCommandRegistry.TryGet(invocation.CommandId, out StudioCommandDescriptor? descriptor))
            throw new ArgumentException($"Unknown Studio command '{invocation.CommandId}'.", nameof(invocation));
        if (invocation.NormalizedValue is double value && (!double.IsFinite(value) || value is < 0 or > 1))
            throw new ArgumentOutOfRangeException(nameof(invocation), "Normalized command values must be between 0 and 1.");
        if (!descriptor!.AcceptsContinuousValue && invocation.NormalizedValue is not null)
            throw new ArgumentException($"Studio command '{invocation.CommandId}' does not accept a continuous value.", nameof(invocation));

        Registration? registration;
        lock (_sync) _handlers.TryGetValue(invocation.CommandId, out registration);
        StudioCommandState state = registration?.State?.Invoke() ?? new(registration is not null);
        return registration is null || !state.IsAvailable
            ? ValueTask.FromResult(new StudioCommandResult(false, state.UnavailableReason ?? "The command is unavailable."))
            : registration.Handler(invocation);
    }

    public void NotifyStateChanged() => StateChanged?.Invoke(this, EventArgs.Empty);

    private void Unregister(Registration registration)
    {
        lock (_sync)
        {
            if (_handlers.TryGetValue(registration.CommandId, out Registration? active) && ReferenceEquals(active, registration))
                _handlers.Remove(registration.CommandId);
        }
        StateChanged?.Invoke(this, EventArgs.Empty);
    }

    private sealed class Registration(StudioCommandDispatcher owner, string commandId,
        Func<StudioCommandInvocation, ValueTask<StudioCommandResult>> handler, Func<StudioCommandState>? state) : IDisposable
    {
        private int _disposed;
        public string CommandId { get; } = commandId;
        public Func<StudioCommandInvocation, ValueTask<StudioCommandResult>> Handler { get; } = handler;
        public Func<StudioCommandState>? State { get; } = state;
        public void Dispose()
        {
            if (Interlocked.Exchange(ref _disposed, 1) == 0) owner.Unregister(this);
        }
    }
}

[Flags]
public enum StudioKeyModifiers { None = 0, Control = 1, Alt = 2, Shift = 4, Windows = 8 }

public sealed record StudioKeyChord(string Key, StudioKeyModifiers Modifiers)
{
    public string DisplayText => Modifiers == StudioKeyModifiers.None ? Key : $"{Modifiers.ToString().Replace(", ", "+")}+{Key}";

    public static StudioKeyChord Parse(string value)
    {
        if (string.IsNullOrWhiteSpace(value)) throw new InvalidDataException("A keybinding chord is required.");
        string[] parts = value.Split('+', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length == 0) throw new InvalidDataException("A keybinding chord is required.");
        StudioKeyModifiers modifiers = StudioKeyModifiers.None;
        foreach (string part in parts[..^1])
        {
            modifiers |= part.ToLowerInvariant() switch
            {
                "ctrl" or "control" => StudioKeyModifiers.Control,
                "alt" => StudioKeyModifiers.Alt,
                "shift" => StudioKeyModifiers.Shift,
                "win" or "windows" => StudioKeyModifiers.Windows,
                _ => throw new InvalidDataException($"Unknown key modifier '{part}'."),
            };
        }
        string key = parts[^1].Trim();
        if (key.Length is < 1 or > 32 || key.Any(char.IsWhiteSpace)) throw new InvalidDataException("The key name is invalid.");
        return new(key.ToUpperInvariant(), modifiers);
    }
}

public sealed record StudioKeyBinding(string CommandId, StudioKeyChord Chord);
public enum StudioMidiMessageKind { Note, ControlChange }
public sealed record StudioMidiBinding(string CommandId, string? DeviceId, StudioMidiMessageKind MessageKind, int Channel, int Number);
public sealed record StudioMidiMessage(string DeviceId, StudioMidiMessageKind MessageKind, int Channel, int Number, double NormalizedValue);
public sealed record StudioQuickControl(int Slot, string CommandId);

public sealed record StudioRemoteControlDocument(
    int SchemaVersion,
    ImmutableArray<StudioKeyBinding> KeyBindings,
    ImmutableArray<StudioMidiBinding> MidiBindings,
    ImmutableArray<StudioQuickControl> QuickControls)
{
    public const int CurrentSchemaVersion = 1;

    public static StudioRemoteControlDocument Default { get; } = new(CurrentSchemaVersion,
    [
        new(StudioCommandIds.TransportPlayPause, new("SPACE", StudioKeyModifiers.None)),
        new(StudioCommandIds.TransportStop, new("ESCAPE", StudioKeyModifiers.None)),
        new(StudioCommandIds.TransportStepBackward, new("LEFT", StudioKeyModifiers.None)),
        new(StudioCommandIds.TransportStepForward, new("RIGHT", StudioKeyModifiers.None)),
    ], [],
    [
        new(1, StudioCommandIds.TransportPlayPause), new(2, StudioCommandIds.TransportStop),
        new(3, StudioCommandIds.TransportStepBackward), new(4, StudioCommandIds.TransportStepForward),
        new(5, StudioCommandIds.MixerSelectedGain), new(6, StudioCommandIds.MixerSelectedPan),
        new(7, StudioCommandIds.MixerSelectedMute), new(8, StudioCommandIds.MixerSelectedSolo),
    ]);
}

public static class StudioRemoteControlCodec
{
    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
        Converters = { new JsonStringEnumConverter(JsonNamingPolicy.SnakeCaseLower) },
    };

    public static string Serialize(StudioRemoteControlDocument document)
    {
        Validate(document);
        return JsonSerializer.Serialize(document, Options);
    }

    public static StudioRemoteControlDocument Deserialize(string json)
    {
        StudioRemoteControlDocument document;
        try { document = JsonSerializer.Deserialize<StudioRemoteControlDocument>(json, Options) ?? throw new InvalidDataException("Remote-control mappings are empty."); }
        catch (JsonException exception) { throw new InvalidDataException("Remote-control mappings are malformed.", exception); }
        Validate(document);
        return document;
    }

    public static void Validate(StudioRemoteControlDocument document)
    {
        ArgumentNullException.ThrowIfNull(document);
        if (document.SchemaVersion != StudioRemoteControlDocument.CurrentSchemaVersion) throw new InvalidDataException($"Unsupported remote-control schema version '{document.SchemaVersion}'.");
        if (document.KeyBindings.IsDefault || document.MidiBindings.IsDefault || document.QuickControls.IsDefault) throw new InvalidDataException("Remote-control mapping arrays must be initialized.");
        if (document.KeyBindings.Any(binding => binding is null || binding.Chord is null || string.IsNullOrWhiteSpace(binding.CommandId)) ||
            document.MidiBindings.Any(binding => binding is null || string.IsNullOrWhiteSpace(binding.CommandId)) ||
            document.QuickControls.Any(control => control is null || string.IsNullOrWhiteSpace(control.CommandId)))
            throw new InvalidDataException("Remote-control mappings contain a missing required value.");
        foreach (string commandId in document.KeyBindings.Select(item => item.CommandId)
                     .Concat(document.MidiBindings.Select(item => item.CommandId)).Concat(document.QuickControls.Select(item => item.CommandId)))
            if (!StudioCommandRegistry.TryGet(commandId, out _)) throw new InvalidDataException($"Unknown Studio command '{commandId}'.");
        foreach (StudioKeyBinding binding in document.KeyBindings)
        {
            StudioKeyChord normalized = StudioKeyChord.Parse(binding.Chord.DisplayText);
            if (normalized != binding.Chord || !Enum.IsDefined(binding.Chord.Modifiers))
                throw new InvalidDataException($"Keybinding for '{binding.CommandId}' is not normalized.");
        }
        if (document.KeyBindings.GroupBy(item => (item.Chord.Key.ToUpperInvariant(), item.Chord.Modifiers)).Any(group => group.Count() > 1))
            throw new InvalidDataException("Two commands cannot use the same keybinding.");
        foreach (StudioMidiBinding binding in document.MidiBindings)
        {
            if (!Enum.IsDefined(binding.MessageKind)) throw new InvalidDataException("The MIDI message kind is invalid.");
            if (binding.DeviceId is not null && string.IsNullOrWhiteSpace(binding.DeviceId))
                throw new InvalidDataException("A MIDI device ID must be non-empty or null for a wildcard mapping.");
            if (binding.Channel is < 1 or > 16 || binding.Number is < 0 or > 127)
                throw new InvalidDataException("MIDI channels must be 1-16 and message numbers must be 0-127.");
        }
        if (document.MidiBindings.GroupBy(item => (item.DeviceId ?? string.Empty, item.MessageKind, item.Channel, item.Number), StringTupleComparer.Instance).Any(group => group.Count() > 1))
            throw new InvalidDataException("Two commands cannot use the same MIDI input mapping.");
        if (document.QuickControls.Length != 8 || document.QuickControls.Select(item => item.Slot).Order().SequenceEqual(Enumerable.Range(1, 8)) is false)
            throw new InvalidDataException("Quick Controls must define each slot from 1 through 8 exactly once.");
    }

    private sealed class StringTupleComparer : IEqualityComparer<(string, StudioMidiMessageKind, int, int)>
    {
        public static StringTupleComparer Instance { get; } = new();
        public bool Equals((string, StudioMidiMessageKind, int, int) x, (string, StudioMidiMessageKind, int, int) y) =>
            StringComparer.Ordinal.Equals(x.Item1, y.Item1) && x.Item2 == y.Item2 && x.Item3 == y.Item3 && x.Item4 == y.Item4;
        public int GetHashCode((string, StudioMidiMessageKind, int, int) value) => HashCode.Combine(StringComparer.Ordinal.GetHashCode(value.Item1), value.Item2, value.Item3, value.Item4);
    }
}

public sealed class StudioRemoteControlStore(string path)
{
    public string Path { get; } = System.IO.Path.GetFullPath(path);

    public StudioRemoteControlDocument Load()
    {
        if (!File.Exists(Path)) return StudioRemoteControlDocument.Default;
        return StudioRemoteControlCodec.Deserialize(File.ReadAllText(Path));
    }

    public void Save(StudioRemoteControlDocument document)
    {
        string json = StudioRemoteControlCodec.Serialize(document);
        string? directory = System.IO.Path.GetDirectoryName(Path);
        if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
        string temporary = $"{Path}.{Guid.NewGuid():N}.tmp";
        try
        {
            File.WriteAllText(temporary, json);
            File.Move(temporary, Path, true);
        }
        finally
        {
            if (File.Exists(temporary)) File.Delete(temporary);
        }
    }
}

public sealed class StudioRemoteControlService
{
    private readonly object _sync = new();
    private readonly StudioRemoteControlStore _store;
    private StudioRemoteControlDocument _document;

    public StudioRemoteControlService(StudioRemoteControlStore store)
    {
        _store = store ?? throw new ArgumentNullException(nameof(store));
        try
        {
            _document = store.Load();
        }
        catch (InvalidDataException exception)
        {
            _document = StudioRemoteControlDocument.Default;
            LoadWarning = $"Saved remote-control mappings were invalid and defaults were loaded. {exception.Message}";
            if (File.Exists(store.Path))
            {
                string quarantinePath = $"{store.Path}.invalid-{DateTime.UtcNow:yyyyMMddHHmmssfff}";
                try { File.Move(store.Path, quarantinePath); }
                catch (IOException) { LoadWarning += " The invalid file could not be quarantined."; }
                catch (UnauthorizedAccessException) { LoadWarning += " The invalid file could not be quarantined."; }
            }
        }
    }

    public event EventHandler? Changed;
    public string? LoadWarning { get; }

    public StudioRemoteControlDocument Document
    {
        get { lock (_sync) return _document; }
    }

    public void Replace(StudioRemoteControlDocument document)
    {
        StudioRemoteControlCodec.Validate(document);
        _store.Save(document);
        lock (_sync) _document = document;
        Changed?.Invoke(this, EventArgs.Empty);
    }

    public void Reset() => Replace(StudioRemoteControlDocument.Default);

    public string? ResolveKey(StudioKeyChord chord)
    {
        ArgumentNullException.ThrowIfNull(chord);
        StudioRemoteControlDocument document = Document;
        return document.KeyBindings.FirstOrDefault(binding =>
            binding.Chord.Modifiers == chord.Modifiers &&
            string.Equals(binding.Chord.Key, chord.Key, StringComparison.OrdinalIgnoreCase))?.CommandId;
    }

    public StudioCommandInvocation? ResolveMidi(StudioMidiMessage message)
    {
        ArgumentNullException.ThrowIfNull(message);
        if (!double.IsFinite(message.NormalizedValue) || message.NormalizedValue is < 0 or > 1)
            throw new ArgumentOutOfRangeException(nameof(message), "Normalized MIDI values must be between 0 and 1.");
        StudioRemoteControlDocument document = Document;
        StudioMidiBinding? binding = document.MidiBindings.FirstOrDefault(candidate =>
            string.Equals(candidate.DeviceId, message.DeviceId, StringComparison.Ordinal) &&
            candidate.MessageKind == message.MessageKind && candidate.Channel == message.Channel && candidate.Number == message.Number)
            ?? document.MidiBindings.FirstOrDefault(candidate => candidate.DeviceId is null &&
                candidate.MessageKind == message.MessageKind && candidate.Channel == message.Channel && candidate.Number == message.Number);
        if (binding is null) return null;
        StudioCommandDescriptor descriptor = StudioCommandRegistry.Commands.Single(command => command.Id == binding.CommandId);
        if (!descriptor.AcceptsContinuousValue && message.MessageKind == StudioMidiMessageKind.ControlChange && message.NormalizedValue < 0.5)
            return null;
        return new(binding.CommandId, "midi", descriptor.AcceptsContinuousValue ? message.NormalizedValue : null);
    }
}
