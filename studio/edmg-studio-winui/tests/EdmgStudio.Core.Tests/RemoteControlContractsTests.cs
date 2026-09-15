using System.Collections.Immutable;
using EdmgStudio.Core.RemoteControl;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class RemoteControlContractsTests
{
    [TestMethod]
    public void Registry_ExposesStableTransportAndMixerCommands()
    {
        Assert.HasCount(8, StudioCommandRegistry.Commands);
        Assert.IsTrue(StudioCommandRegistry.TryGet(StudioCommandIds.TransportPlayPause, out StudioCommandDescriptor? transport));
        Assert.IsFalse(transport!.AcceptsContinuousValue);
        Assert.IsTrue(StudioCommandRegistry.TryGet(StudioCommandIds.MixerSelectedGain, out StudioCommandDescriptor? gain));
        Assert.IsTrue(gain!.AcceptsContinuousValue);
    }

    [TestMethod]
    public async Task Dispatcher_UsesRegisteredHandlerAndAvailability()
    {
        var dispatcher = new StudioCommandDispatcher();
        bool available = false;
        int calls = 0;
        using IDisposable registration = dispatcher.Register(
            StudioCommandIds.TransportPlayPause,
            invocation =>
            {
                calls++;
                Assert.AreEqual("keyboard", invocation.Source);
                return ValueTask.FromResult(new StudioCommandResult(true));
            },
            () => new StudioCommandState(available, "Load a timeline."));

        StudioCommandResult unavailable = await dispatcher.DispatchAsync(new(StudioCommandIds.TransportPlayPause, "keyboard"));
        Assert.IsFalse(unavailable.Executed);
        Assert.AreEqual(0, calls);

        available = true;
        StudioCommandResult executed = await dispatcher.DispatchAsync(new(StudioCommandIds.TransportPlayPause, "keyboard"));
        Assert.IsTrue(executed.Executed);
        Assert.AreEqual(1, calls);
    }

    [TestMethod]
    public void KeyChord_NormalizesAndRejectsUnknownModifiers()
    {
        StudioKeyChord chord = StudioKeyChord.Parse(" shift + ctrl + k ");
        Assert.AreEqual("K", chord.Key);
        Assert.AreEqual(StudioKeyModifiers.Shift | StudioKeyModifiers.Control, chord.Modifiers);
        Assert.Throws<InvalidDataException>(() => StudioKeyChord.Parse("hyper+k"));
    }

    [TestMethod]
    public void Codec_RoundTripsDefaultMapping()
    {
        string json = StudioRemoteControlCodec.Serialize(StudioRemoteControlDocument.Default);
        StudioRemoteControlDocument restored = StudioRemoteControlCodec.Deserialize(json);

        Assert.HasCount(4, restored.KeyBindings);
        Assert.HasCount(8, restored.QuickControls);
        Assert.AreEqual(StudioCommandIds.MixerSelectedSolo, restored.QuickControls[7].CommandId);
    }

    [TestMethod]
    public void Codec_RejectsKeyAndMidiConflictsBeforeImport()
    {
        StudioRemoteControlDocument defaults = StudioRemoteControlDocument.Default;
        StudioKeyChord chord = new("K", StudioKeyModifiers.Control);
        var keyConflict = defaults with
        {
            KeyBindings =
            [
                new(StudioCommandIds.TransportPlayPause, chord),
                new(StudioCommandIds.TransportStop, chord),
            ]
        };
        Assert.Throws<InvalidDataException>(() => StudioRemoteControlCodec.Serialize(keyConflict));

        var midiConflict = defaults with
        {
            MidiBindings =
            [
                new(StudioCommandIds.TransportPlayPause, "device", StudioMidiMessageKind.Note, 1, 60),
                new(StudioCommandIds.TransportStop, "device", StudioMidiMessageKind.Note, 1, 60),
            ]
        };
        Assert.Throws<InvalidDataException>(() => StudioRemoteControlCodec.Serialize(midiConflict));
    }

    [TestMethod]
    public void Codec_RequiresExactlyEightQuickControlSlots()
    {
        StudioRemoteControlDocument invalid = StudioRemoteControlDocument.Default with
        {
            QuickControls = ImmutableArray.Create(new StudioQuickControl(1, StudioCommandIds.TransportPlayPause))
        };
        Assert.Throws<InvalidDataException>(() => StudioRemoteControlCodec.Serialize(invalid));
    }

    [TestMethod]
    public void Store_ReplacesOnlyAfterDocumentValidation()
    {
        string directory = System.IO.Path.Combine(System.IO.Path.GetTempPath(), $"edmg-remote-{Guid.NewGuid():N}");
        string path = System.IO.Path.Combine(directory, "mappings.json");
        try
        {
            var store = new StudioRemoteControlStore(path);
            store.Save(StudioRemoteControlDocument.Default);
            string accepted = File.ReadAllText(path);

            StudioRemoteControlDocument invalid = StudioRemoteControlDocument.Default with { SchemaVersion = 2 };
            Assert.Throws<InvalidDataException>(() => store.Save(invalid));
            Assert.AreEqual(accepted, File.ReadAllText(path));
        }
        finally
        {
            if (Directory.Exists(directory)) Directory.Delete(directory, true);
        }
    }

    [TestMethod]
    public async Task Dispatcher_RejectsUnknownAndInvalidValuesAndStopsAfterDisposal()
    {
        var dispatcher = new StudioCommandDispatcher();
        int calls = 0;
        IDisposable registration = dispatcher.Register(
            StudioCommandIds.MixerSelectedGain,
            _ =>
            {
                calls++;
                return ValueTask.FromResult(new StudioCommandResult(true));
            });

        await Assert.ThrowsAsync<ArgumentException>(async () =>
            await dispatcher.DispatchAsync(new("unknown", "test")));
        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(async () =>
            await dispatcher.DispatchAsync(new(StudioCommandIds.MixerSelectedGain, "test", double.NaN)));
        await Assert.ThrowsAsync<ArgumentException>(async () =>
            await dispatcher.DispatchAsync(new(StudioCommandIds.TransportStop, "test", 0.5)));

        registration.Dispose();
        StudioCommandResult result = await dispatcher.DispatchAsync(new(StudioCommandIds.MixerSelectedGain, "test", 0.5));
        Assert.IsFalse(result.Executed);
        Assert.AreEqual(0, calls);
    }

    [TestMethod]
    public void Codec_RejectsMalformedUnsupportedAndUnnormalizedDocuments()
    {
        Assert.Throws<InvalidDataException>(() => StudioRemoteControlCodec.Deserialize("{"));
        string unsupported = StudioRemoteControlCodec.Serialize(StudioRemoteControlDocument.Default)
            .Replace("\"schemaVersion\": 1", "\"schemaVersion\": 2", StringComparison.Ordinal);
        Assert.Throws<InvalidDataException>(() => StudioRemoteControlCodec.Deserialize(unsupported));

        StudioRemoteControlDocument unnormalized = StudioRemoteControlDocument.Default with
        {
            KeyBindings = [new(StudioCommandIds.TransportPlayPause, new("space", StudioKeyModifiers.None))]
        };
        Assert.Throws<InvalidDataException>(() => StudioRemoteControlCodec.Serialize(unnormalized));
        string nullBinding = StudioRemoteControlCodec.Serialize(StudioRemoteControlDocument.Default)
            .Replace("\"keyBindings\": [", "\"keyBindings\": [null,", StringComparison.Ordinal);
        Assert.Throws<InvalidDataException>(() => StudioRemoteControlCodec.Deserialize(nullBinding));
    }

    [TestMethod]
    public void Service_PreservesAcceptedStateWhenReplacementFails()
    {
        string directory = System.IO.Path.Combine(System.IO.Path.GetTempPath(), $"edmg-remote-{Guid.NewGuid():N}");
        string path = System.IO.Path.Combine(directory, "mappings.json");
        try
        {
            var service = new StudioRemoteControlService(new StudioRemoteControlStore(path));
            StudioRemoteControlDocument accepted = service.Document;

            Assert.Throws<InvalidDataException>(() => service.Replace(accepted with { QuickControls = [] }));

            Assert.AreSame(accepted, service.Document);
            Assert.IsFalse(File.Exists(path));
        }
        finally
        {
            if (Directory.Exists(directory)) Directory.Delete(directory, true);
        }
    }

    [TestMethod]
    public void Service_PrefersDeviceSpecificMidiMappingAndRejectsInvalidValues()
    {
        string directory = System.IO.Path.Combine(System.IO.Path.GetTempPath(), $"edmg-remote-{Guid.NewGuid():N}");
        try
        {
            var service = new StudioRemoteControlService(new StudioRemoteControlStore(System.IO.Path.Combine(directory, "mappings.json")));
            service.Replace(service.Document with
            {
                MidiBindings =
                [
                    new(StudioCommandIds.TransportStop, null, StudioMidiMessageKind.Note, 1, 60),
                    new(StudioCommandIds.TransportPlayPause, "device", StudioMidiMessageKind.Note, 1, 60),
                ]
            });

            StudioCommandInvocation? specific = service.ResolveMidi(new("device", StudioMidiMessageKind.Note, 1, 60, 1));
            StudioCommandInvocation? wildcard = service.ResolveMidi(new("other", StudioMidiMessageKind.Note, 1, 60, 1));
            Assert.AreEqual(StudioCommandIds.TransportPlayPause, specific?.CommandId);
            Assert.AreEqual(StudioCommandIds.TransportStop, wildcard?.CommandId);
            Assert.Throws<ArgumentOutOfRangeException>(() =>
                service.ResolveMidi(new("device", StudioMidiMessageKind.Note, 1, 60, 1.1)));
        }
        finally
        {
            if (Directory.Exists(directory)) Directory.Delete(directory, true);
        }
    }

    [TestMethod]
    public void Service_RecoversFromAndQuarantinesDamagedPersistedMappings()
    {
        string directory = System.IO.Path.Combine(System.IO.Path.GetTempPath(), $"edmg-remote-{Guid.NewGuid():N}");
        string path = System.IO.Path.Combine(directory, "mappings.json");
        Directory.CreateDirectory(directory);
        File.WriteAllText(path, "{");
        try
        {
            var service = new StudioRemoteControlService(new StudioRemoteControlStore(path));

            Assert.IsNotNull(service.LoadWarning);
            Assert.AreSame(StudioRemoteControlDocument.Default, service.Document);
            Assert.IsFalse(File.Exists(path));
            Assert.HasCount(1, Directory.GetFiles(directory, "mappings.json.invalid-*"));
        }
        finally
        {
            if (Directory.Exists(directory)) Directory.Delete(directory, true);
        }
    }
}
