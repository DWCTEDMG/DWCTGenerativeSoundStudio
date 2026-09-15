using EdmgStudio.Core.RemoteControl;
using Microsoft.UI.Dispatching;
using Windows.Devices.Enumeration;
using Windows.Devices.Midi;

namespace EdmgStudio.WinUI.Services;

public sealed record MidiInputDeviceDescriptor(string Id, string Name);

public sealed class WindowsMidiInputService(
    IStudioCommandDispatcher dispatcher,
    StudioRemoteControlService remoteControl) : IAsyncDisposable
{
    private readonly DispatcherQueue _dispatcherQueue = DispatcherQueue.GetForCurrentThread()
        ?? throw new InvalidOperationException("MIDI input must be created on the Studio UI thread.");
    private readonly HashSet<(string DeviceId, int Channel, int Number)> _activeDiscreteControls = [];
    private MidiInPort? _port;
    private bool _learning;

    public event EventHandler<StudioMidiMessage>? MessageLearned;
    public event EventHandler<string>? StatusChanged;

    public string? SelectedDeviceId { get; private set; }

    public async Task<IReadOnlyList<MidiInputDeviceDescriptor>> DiscoverAsync()
    {
        DeviceInformationCollection devices = await DeviceInformation.FindAllAsync(MidiInPort.GetDeviceSelector());
        return devices.Select(device => new MidiInputDeviceDescriptor(device.Id, device.Name)).ToArray();
    }

    public async Task SelectDeviceAsync(string? deviceId)
    {
        await ClosePortAsync();
        if (string.IsNullOrWhiteSpace(deviceId))
        {
            StatusChanged?.Invoke(this, "No MIDI input selected.");
            return;
        }

        _port = await MidiInPort.FromIdAsync(deviceId)
            ?? throw new InvalidOperationException("The selected MIDI input is unavailable or disconnected.");
        SelectedDeviceId = deviceId;
        _port.MessageReceived += Port_MessageReceived;
        StatusChanged?.Invoke(this, "MIDI input connected.");
    }

    public void BeginLearn()
    {
        if (_port is null) throw new InvalidOperationException("Select a connected MIDI input before learning a mapping.");
        _learning = true;
        StatusChanged?.Invoke(this, "MIDI learn is listening for a note or control-change message.");
    }

    public void CancelLearn() => _learning = false;

    private void Port_MessageReceived(MidiInPort sender, MidiMessageReceivedEventArgs args)
    {
        StudioMidiMessage? message = args.Message switch
        {
            MidiNoteOnMessage note when note.Velocity > 0 =>
                new(sender.DeviceId, StudioMidiMessageKind.Note, note.Channel + 1, note.Note, note.Velocity / 127d),
            MidiControlChangeMessage control =>
                new(sender.DeviceId, StudioMidiMessageKind.ControlChange, control.Channel + 1, control.Controller, control.ControlValue / 127d),
            _ => null,
        };
        if (message is null) return;
        if (_learning)
        {
            _learning = false;
            MessageLearned?.Invoke(this, message);
            return;
        }

        StudioCommandInvocation? invocation = remoteControl.ResolveMidi(message);
        if (message.MessageKind == StudioMidiMessageKind.ControlChange)
        {
            var control = (message.DeviceId, message.Channel, message.Number);
            if (invocation is null)
            {
                _activeDiscreteControls.Remove(control);
                return;
            }
            if (StudioCommandRegistry.TryGet(invocation.CommandId, out StudioCommandDescriptor? descriptor) &&
                !descriptor!.AcceptsContinuousValue && !_activeDiscreteControls.Add(control))
                return;
        }
        if (invocation is not null)
            _dispatcherQueue.TryEnqueue(() => _ = ObserveDispatchAsync(dispatcher.DispatchAsync(invocation)));
    }

    private Task ClosePortAsync()
    {
        _learning = false;
        _activeDiscreteControls.Clear();
        SelectedDeviceId = null;
        if (_port is null) return Task.CompletedTask;
        _port.MessageReceived -= Port_MessageReceived;
        _port.Dispose();
        _port = null;
        return Task.CompletedTask;
    }

    private async Task ObserveDispatchAsync(ValueTask<StudioCommandResult> dispatch)
    {
        try
        {
            StudioCommandResult result = await dispatch;
            if (!result.Executed && !string.IsNullOrWhiteSpace(result.Message))
                StatusChanged?.Invoke(this, result.Message);
        }
        catch (Exception exception) when (exception is ArgumentException or InvalidOperationException)
        {
            StatusChanged?.Invoke(this, exception.Message);
        }
    }

    public async ValueTask DisposeAsync() => await ClosePortAsync();
}
