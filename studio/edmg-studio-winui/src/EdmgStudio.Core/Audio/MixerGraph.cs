using System.Collections.Immutable;

namespace EdmgStudio.Core.Audio;

public enum MixerChannelKind { Track, Group, FxReturn, Master }
public enum MixerTap { PreFader, PostFader }
public sealed record MixerInsert(
    string Id, int LatencySamples, bool Enabled = true, bool Bypassed = false,
    string? PluginId = null, string? PresetName = null, string? StateBase64 = null,
    string? ModulePath = null, string? ModuleSha256 = null);
public sealed record MixerSend(string Id, string DestinationId, MixerTap Tap, float Gain);
public sealed record MixerChannel(
    string Id, string Name, MixerChannelKind Kind, string? OutputId,
    ImmutableArray<MixerInsert> Inserts, ImmutableArray<MixerSend> Sends,
    float Gain = 1, float Pan = 0, bool Muted = false, bool Solo = false,
    bool RecordArmed = false, bool InputMonitoring = false,
    string Color = "#607D8B", bool Visible = true);
public sealed record MixerChannelLatency(string ChannelId, long InputSamples, long InsertSamples, long OutputSamples);
public sealed record MixerRouteDelay(string Id, string SourceId, string DestinationId, MixerTap Tap, float Gain, long DelaySamples);
public sealed record MixerGraphPlan(
    ImmutableArray<MixerChannel> ProcessingOrder,
    ImmutableArray<MixerChannelLatency> Latencies,
    ImmutableArray<MixerRouteDelay> Routes,
    ImmutableArray<string> AudibleChannelIds,
    long TotalLatencySamples);

public sealed record MixerSnapshot(long Revision, MixerGraphPlan Plan);

public sealed class MixerService
{
    private MixerSnapshot _current = new(0, MixerGraphBuilder.Build([
        new MixerChannel("master", "Master", MixerChannelKind.Master, null, [], [])]));

    public MixerSnapshot Current => Volatile.Read(ref _current);

    public MixerSnapshot Replace(IEnumerable<MixerChannel> channels)
    {
        MixerGraphPlan plan = MixerGraphBuilder.Build(channels);
        while (true)
        {
            MixerSnapshot current = Current;
            var replacement = new MixerSnapshot(checked(current.Revision + 1), plan);
            if (ReferenceEquals(Interlocked.CompareExchange(ref _current, replacement, current), current))
                return replacement;
        }
    }
}

/// <summary>Builds a control-thread routing/PDC plan. It does not claim native plugin processing.</summary>
public static class MixerGraphBuilder
{
    public static MixerGraphPlan Build(IEnumerable<MixerChannel> channels)
    {
        ArgumentNullException.ThrowIfNull(channels);
        MixerChannel[] snapshot = channels.OrderBy(channel => channel.Id, StringComparer.Ordinal).ToArray();
        if (snapshot.Any(channel => string.IsNullOrWhiteSpace(channel.Id) || !Enum.IsDefined(channel.Kind) ||
                                    channel.Inserts.IsDefault || channel.Sends.IsDefault) ||
            snapshot.Select(channel => channel.Id).Distinct(StringComparer.Ordinal).Count() != snapshot.Length)
            throw new ArgumentException("Mixer channels require unique IDs and initialized insert/send lists.");
        MixerChannel[] masters = snapshot.Where(channel => channel.Kind == MixerChannelKind.Master).ToArray();
        if (masters.Length != 1)
            throw new ArgumentException("The mixer requires exactly one master channel.");
        var byId = snapshot.ToDictionary(channel => channel.Id, StringComparer.Ordinal);
        var edges = new List<MixerRouteDelay>();
        foreach (MixerChannel channel in snapshot)
        {
            if (channel.Inserts.Any(insert => string.IsNullOrWhiteSpace(insert.Id) || insert.LatencySamples < 0) ||
                channel.Inserts.Select(insert => insert.Id).Distinct(StringComparer.Ordinal).Count() != channel.Inserts.Length ||
                !float.IsFinite(channel.Gain) || channel.Gain < 0 ||
                !float.IsFinite(channel.Pan) || channel.Pan is < -1 or > 1)
                throw new ArgumentException($"Channel '{channel.Id}' has invalid or duplicate inserts.");
            if (channel.Kind == MixerChannelKind.Master)
            {
                if (channel.OutputId is not null || channel.Sends.Length != 0)
                    throw new ArgumentException("The master cannot route back into the mixer.");
            }
            else
            {
                AddRoute("output", channel, channel.OutputId, MixerTap.PostFader, 1);
            }
            if (channel.Sends.Select(send => send.Id).Distinct(StringComparer.Ordinal).Count() != channel.Sends.Length)
                throw new ArgumentException($"Channel '{channel.Id}' has duplicate sends.");
            foreach (MixerSend send in channel.Sends)
            {
                if (string.IsNullOrWhiteSpace(send.Id)) throw new ArgumentException("Send IDs cannot be empty.");
                AddRoute("send:" + send.Id, channel, send.DestinationId, send.Tap, send.Gain);
            }
        }

        var incoming = snapshot.ToDictionary(channel => channel.Id,
            channel => edges.Where(edge => edge.DestinationId == channel.Id).ToArray(), StringComparer.Ordinal);
        var outgoing = snapshot.ToDictionary(channel => channel.Id,
            channel => edges.Where(edge => edge.SourceId == channel.Id).ToArray(), StringComparer.Ordinal);
        var remaining = incoming.ToDictionary(pair => pair.Key, pair => pair.Value.Length, StringComparer.Ordinal);
        var ready = new SortedSet<string>(remaining.Where(pair => pair.Value == 0).Select(pair => pair.Key), StringComparer.Ordinal);
        var order = ImmutableArray.CreateBuilder<MixerChannel>();
        var latency = new Dictionary<string, MixerChannelLatency>(StringComparer.Ordinal);
        var routes = ImmutableArray.CreateBuilder<MixerRouteDelay>();
        while (ready.Count > 0)
        {
            string id = ready.Min!;
            ready.Remove(id);
            MixerChannel channel = byId[id];
            long SourceLatency(MixerRouteDelay edge) => edge.Tap == MixerTap.PreFader
                ? latency[edge.SourceId].InputSamples + latency[edge.SourceId].InsertSamples
                : latency[edge.SourceId].OutputSamples;
            long input = incoming[id].Select(SourceLatency).DefaultIfEmpty(0).Max();
            // Bypassed inserts retain latency; disabled inserts are removed from the processing graph.
            long inserts = channel.Inserts.Where(insert => insert.Enabled).Sum(insert => (long)insert.LatencySamples);
            latency[id] = new(id, input, inserts, checked(input + inserts));
            foreach (MixerRouteDelay edge in incoming[id])
                routes.Add(edge with { DelaySamples = input - SourceLatency(edge) });
            order.Add(channel);
            foreach (MixerRouteDelay edge in outgoing[id])
                if (--remaining[edge.DestinationId] == 0) ready.Add(edge.DestinationId);
        }
        if (order.Count != snapshot.Length)
            throw new ArgumentException("Mixer routing contains a feedback cycle.");
        ImmutableArray<string> audibleChannelIds = CalculateAudibleChannels(snapshot, outgoing, masters[0].Id);
        return new(order.ToImmutable(), order.Select(channel => latency[channel.Id]).ToImmutableArray(),
            routes.OrderBy(route => route.SourceId, StringComparer.Ordinal).ThenBy(route => route.Id, StringComparer.Ordinal).ToImmutableArray(),
            audibleChannelIds,
            latency[masters[0].Id].OutputSamples);

        void AddRoute(string id, MixerChannel source, string? destination, MixerTap tap, float gain)
        {
            if (destination is null || !byId.TryGetValue(destination, out MixerChannel? target) ||
                target.Kind == MixerChannelKind.Track || !Enum.IsDefined(tap) || !float.IsFinite(gain) || gain < 0)
                throw new ArgumentException($"Channel '{source.Id}' has an invalid route or destination '{destination}'.");
            edges.Add(new(id, source.Id, destination, tap, gain, 0));
        }
    }

    private static ImmutableArray<string> CalculateAudibleChannels(
        IReadOnlyList<MixerChannel> channels,
        IReadOnlyDictionary<string, MixerRouteDelay[]> outgoing,
        string masterId)
    {
        var byId = channels.ToDictionary(channel => channel.Id, StringComparer.Ordinal);
        string[] soloIds = channels.Where(channel => channel.Solo).Select(channel => channel.Id).ToArray();
        var audible = ImmutableArray.CreateBuilder<string>();
        foreach (MixerChannel channel in channels.OrderBy(item => item.Id, StringComparer.Ordinal))
        {
            if (channel.Muted || !CanReachMaster(channel.Id, new HashSet<string>(StringComparer.Ordinal)))
                continue;
            if (soloIds.Length == 0 || soloIds.Any(soloId =>
                    CanReach(channel.Id, soloId, new HashSet<string>(StringComparer.Ordinal)) ||
                    CanReach(soloId, channel.Id, new HashSet<string>(StringComparer.Ordinal))))
                audible.Add(channel.Id);
        }
        return audible.ToImmutable();

        bool CanReachMaster(string id, HashSet<string> visited)
        {
            if (!visited.Add(id) || byId[id].Muted) return false;
            if (id == masterId) return true;
            return outgoing[id].Any(route => CanReachMaster(route.DestinationId, visited));
        }

        bool CanReach(string sourceId, string destinationId, HashSet<string> visited)
        {
            if (!visited.Add(sourceId) || byId[sourceId].Muted) return false;
            if (sourceId == destinationId) return true;
            return outgoing[sourceId].Any(route => CanReach(route.DestinationId, destinationId, visited));
        }
    }

    public static MixerGraphPlan FromAudioRoutes(AudioEngineConfiguration configuration)
    {
        string masterId = "master";
        while (configuration.Tracks.Any(track => track.TrackId == masterId)) masterId = "_" + masterId;
        // Preserve the compatibility engine's case-insensitive master route without consuming a track ID.
        IEnumerable<MixerChannel> tracks = configuration.Tracks.Select(track => new MixerChannel(
            track.TrackId, track.TrackId, MixerChannelKind.Track,
            string.Equals(track.OutputBusId, "master", StringComparison.OrdinalIgnoreCase) ? masterId : track.OutputBusId, [], [],
            track.Gain, track.Pan, track.Muted, track.Solo));
        return Build(tracks.Append(new MixerChannel(masterId, "Master", MixerChannelKind.Master, null, [], [])));
    }
}
