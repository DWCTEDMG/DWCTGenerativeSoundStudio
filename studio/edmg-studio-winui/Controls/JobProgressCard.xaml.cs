using EdmgStudio.Core.Models;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EdmgStudio.WinUI.Controls;

public sealed partial class JobProgressCard : UserControl
{
    private StudioJob? _job;

    public JobProgressCard() => InitializeComponent();

    public event EventHandler<StudioJob>? PauseRequested;

    public event EventHandler<StudioJob>? CancelRequested;

    public event EventHandler? OpenQueueRequested;

    public void UpdateJob(StudioJob? job)
    {
        _job = job;
        Visibility = job is null ? Visibility.Collapsed : Visibility.Visible;
        if (job is null)
        {
            return;
        }

        double percent = Math.Clamp(job.Progress?.Percent ?? 0, 0, 100);
        TitleText.Text = $"{FormatLabel(job.Type)} · {ShortId(job.Id)}";
        StageText.Text = job.Progress?.Message ?? job.Progress?.Stage ?? FormatLabel(job.Status);
        JobProgress.Value = percent;
        JobProgress.IsIndeterminate = !job.Progress?.Percent.HasValue ?? true;
        EtaText.Text = EstimateEta(job, percent);
        PauseButton.IsEnabled = job.CanPause;
        CancelButton.IsEnabled = job.CanCancel;
    }

    private void PauseButton_Click(object sender, RoutedEventArgs e)
    {
        if (_job is not null)
        {
            PauseRequested?.Invoke(this, _job);
        }
    }

    private void CancelButton_Click(object sender, RoutedEventArgs e)
    {
        if (_job is not null)
        {
            CancelRequested?.Invoke(this, _job);
        }
    }

    private void OpenQueueButton_Click(object sender, RoutedEventArgs e) => OpenQueueRequested?.Invoke(this, EventArgs.Empty);

    private static string EstimateEta(StudioJob job, double percent)
    {
        if (percent <= 0 || percent >= 100 || !DateTimeOffset.TryParse(job.StartedAt, out DateTimeOffset started))
        {
            return $"{percent:0}% · ETA calculating";
        }

        double remainingSeconds = (DateTimeOffset.UtcNow - started).TotalSeconds * (100 - percent) / percent;
        if (!double.IsFinite(remainingSeconds) || remainingSeconds < 0)
        {
            return $"{percent:0}% · ETA calculating";
        }

        TimeSpan remaining = TimeSpan.FromSeconds(Math.Min(remainingSeconds, TimeSpan.FromDays(7).TotalSeconds));
        string eta = remaining.TotalHours >= 1 ? $"{remaining:h\\:mm\\:ss}" : $"{remaining:mm\\:ss}";
        return $"{percent:0}% · ETA {eta}";
    }

    private static string FormatLabel(string value) => value.Replace('_', ' ');

    private static string ShortId(string value) => value.Length <= 8 ? value : value[..8];
}
