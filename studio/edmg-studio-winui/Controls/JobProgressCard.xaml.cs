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

        RenderQueueJobSummary summary = RenderQueueJobSummary.Create(job);
        TitleText.Text = summary.Title;
        StageText.Text = summary.StageLabel;
        JobProgress.Value = summary.Percent;
        JobProgress.IsIndeterminate = !job.Progress?.Percent.HasValue ?? true;
        EtaText.Text = $"{summary.ProgressLabel} · {summary.EtaLabel}";
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
}
