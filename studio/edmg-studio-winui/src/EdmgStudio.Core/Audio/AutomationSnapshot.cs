using System.Collections.Immutable;
using EdmgStudio.Core.Models;

namespace EdmgStudio.Core.Audio;

public readonly record struct AutomationSamplePoint(long Sample, double Value, AutomationCurve Curve, double Tension);

public sealed class AutomationLaneSnapshot
{
    private readonly AutomationSamplePoint[] _points;
    public AutomationLaneSnapshot(string laneId, string trackId, string target, AutomationMode mode, double defaultValue,
        ImmutableArray<AutomationSamplePoint> points)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(laneId); ArgumentException.ThrowIfNullOrWhiteSpace(trackId);
        ProfessionalEditingContracts.ValidateTarget(target);
        if (!Enum.IsDefined(mode)) throw new ArgumentOutOfRangeException(nameof(mode));
        if (!double.IsFinite(defaultValue) || points.IsDefault || points.Length > ProfessionalEditingContracts.MaximumPointsPerLane) throw new ArgumentOutOfRangeException(nameof(defaultValue));
        long previous = -1;
        foreach (var point in points)
        {
            if (point.Sample <= previous || !double.IsFinite(point.Value) || !double.IsFinite(point.Tension) ||
                point.Tension is < -1 or > 1 || !Enum.IsDefined(point.Curve))
                throw new ArgumentException("Automation points must be finite, valid, and strictly ordered.", nameof(points));
            previous = point.Sample;
        }
        LaneId=laneId; TrackId=trackId; Target=target; Mode=mode; DefaultValue=defaultValue; _points=points.ToArray();
    }
    public string LaneId { get; }
    public string TrackId { get; }
    public string Target { get; }
    public AutomationMode Mode { get; }
    public double DefaultValue { get; }
    public int PointCount => _points.Length;

    public double Evaluate(long sample)
    {
        if (_points.Length==0 || sample<_points[0].Sample) return DefaultValue;
        int lo=0, hi=_points.Length-1;
        while(lo<=hi){int mid=lo+((hi-lo)>>1); if(_points[mid].Sample<=sample) lo=mid+1; else hi=mid-1;}
        int left=hi;
        if(left==_points.Length-1 || sample==_points[left].Sample || _points[left].Curve==AutomationCurve.Step) return _points[left].Value;
        ref readonly AutomationSamplePoint a=ref _points[left]; ref readonly AutomationSamplePoint b=ref _points[left+1];
        double t=(double)(sample-a.Sample)/(b.Sample-a.Sample);
        if(a.Curve==AutomationCurve.Smooth)
        {
            double smooth=t*t*(3-2*t);
            double shaped=a.Tension>=0 ? Math.Pow(smooth,1+a.Tension*3) : 1-Math.Pow(1-smooth,1-a.Tension*3);
            t=shaped;
        }
        return a.Value+(b.Value-a.Value)*t;
    }
}

public sealed record AudioAutomationSnapshot(ImmutableArray<AutomationLaneSnapshot> Lanes)
{
    public static AudioAutomationSnapshot Empty { get; } = new([]);

    public AutomationLaneSnapshot? FindLane(string trackId, string target)
    {
        foreach (AutomationLaneSnapshot lane in Lanes)
            if (string.Equals(lane.TrackId, trackId, StringComparison.Ordinal) &&
                string.Equals(lane.Target, target, StringComparison.Ordinal))
                return lane;
        return null;
    }

    public AutomationLaneSnapshot? FindSendLane(string trackId, string destinationId)
    {
        foreach (AutomationLaneSnapshot lane in Lanes)
            if (string.Equals(lane.TrackId, trackId, StringComparison.Ordinal) &&
                lane.Target.StartsWith("send:", StringComparison.Ordinal) &&
                lane.Target.AsSpan(5).SequenceEqual(destinationId))
                return lane;
        return null;
    }

    public static AudioAutomationSnapshot Build(CanonicalProject project)
    {
        ProfessionalEditingDocument document = ProfessionalEditingContracts.Read(project.Timeline);
        ProfessionalEditingContracts.ValidateAgainstProject(project, document);
        MixerDocument mixer = MixerDocumentCodec.ReadOrMigrate(project.Timeline, project);
        IReadOnlyDictionary<string, MixerChannelDocument> channels = mixer.Channels
            .ToDictionary(channel => channel.Id, StringComparer.Ordinal);
        return new(document.AutomationLanes.Select(lane => new AutomationLaneSnapshot(
            lane.Id,
            lane.TrackId,
            lane.Target,
            lane.Mode,
            DefaultValue(lane, channels),
            lane.Points.Select(point => new AutomationSamplePoint(
                point.Sample,
                point.Value,
                point.Curve,
                point.Tension)).ToImmutableArray())).ToImmutableArray());
    }

    private static double DefaultValue(
        AutomationLane lane,
        IReadOnlyDictionary<string, MixerChannelDocument> channels)
    {
        if (!channels.TryGetValue(lane.TrackId, out MixerChannelDocument? channel))
        {
            return lane.Target == "volume" ? 1 : 0;
        }

        if (lane.Target == "volume")
        {
            return channel.Gain;
        }

        if (lane.Target == "pan")
        {
            return channel.Pan;
        }

        if (lane.Target.StartsWith("send:", StringComparison.Ordinal))
        {
            string destinationId = lane.Target[5..];
            return channel.Sends.FirstOrDefault(send =>
                send.Enabled && string.Equals(send.DestinationId, destinationId, StringComparison.Ordinal))?.Gain ?? 0;
        }

        return 0;
    }
}
