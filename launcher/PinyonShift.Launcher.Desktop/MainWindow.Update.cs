using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Interactivity;
using PinyonShift.Launcher.Updates;

namespace PinyonShift.Launcher.Desktop;

// FB-10.7: update from inside the launcher, as on Windows. The first click
// on "Update to <version>" explains what happens; the second downloads the
// release beside the launcher (the .app bundle on macOS), checks GitHub's
// SHA-256, swaps it in and starts the new launcher. Saves, settings and game
// files under the install root stay.
public partial class MainWindow
{
    private AvailableUpdate? _update;
    private bool _updateConfirming;

    private string? ReleaseJson => _installation is null ? null
        : Path.Combine(_installation.Root, "config", "release.json");

    private string CurrentReleaseVersion() =>
        ReleaseJson is { } json && LauncherUpdate.ReadRelease(json) is { } release ? release.Version : Installation.Version;

    private async Task StartUpdateCheckAsync()
    {
        if (ReleaseJson is not { } json) return;
        VersionText.Text = $"Pinyon Shift {CurrentReleaseVersion()} · Not affiliated with Microsoft or Playground Games";
        var arguments = Environment.GetCommandLineArgs();
        var updated = Array.IndexOf(arguments, LauncherUpdate.UpdatedArgument);
        if (updated > 0 && updated + 1 < arguments.Length)
            StatusText.Text = $"Updated from Pinyon Shift {arguments[updated + 1]}. Your saves and settings were kept.";
        try { await LauncherUpdate.CleanUpAsync(LauncherUpdate.InstalledLauncher()); }
        catch (Exception error) { AppendLog($"Could not remove the previous launcher's files: {error.Message}"); }
        // Released launchers only; a checkout updates with git.
        if (!File.Exists(Path.Combine(_installation!.Root, ".pinyon-source-sha256")) || !LauncherUpdate.CheckEnabled)
            return;
        try
        {
            using var client = LauncherUpdate.CreateClient(CurrentReleaseVersion());
            _update = await LauncherUpdate.CheckAsync(client, json, CancellationToken.None);
        }
        catch (Exception error)
        {
            AppendLog($"Could not check for updates: {error.Message}");
            return;
        }
        if (_update is null) return;
        UpdateButton.Content = $"Update to {_update.Version}";
        UpdateButton.IsVisible = true;
        AppendLog($"Pinyon Shift {_update.Version} is available: {_update.ReleaseUrl}");
    }

    private async void Update_Click(object? sender, RoutedEventArgs e)
    {
        if (_update is not { } update) return;
        if (_mode is Mode.Building or Mode.Playing or Mode.Loading)
        {
            StatusText.Text = "Close the game and wait for the build to finish, then update.";
            return;
        }
        if (!_updateConfirming)
        {
            _updateConfirming = true;
            var size = update.Size > 0 ? $" ({update.Size / (1024.0 * 1024.0):0} MB)" : "";
            StatusText.Text = $"Pinyon Shift {update.Version}{size} downloads from GitHub and the launcher restarts. "
                + "Your saves, settings and game files stay; the new version is then built from your disc image.";
            UpdateButton.Content = "Download and restart";
            return;
        }

        var installed = LauncherUpdate.InstalledLauncher();
        try { LauncherUpdate.EnsureWritable(installed); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            StatusText.Text = $"The launcher's folder cannot be changed ({installed}). Move the launcher to a folder "
                + "you own, or download the new release from GitHub.";
            if (update.ReleaseUrl.StartsWith("https://", StringComparison.Ordinal)) Installation.Open(update.ReleaseUrl);
            return;
        }

        UpdateButton.IsEnabled = false;
        PrimaryButton.IsEnabled = false;
        var staging = LauncherUpdate.StagingRoot(installed);
        try
        {
            _cancel?.Dispose();
            _cancel = new CancellationTokenSource();
            using var client = LauncherUpdate.CreateClient(CurrentReleaseVersion());
            var progress = new Progress<double>(fraction =>
                StatusText.Text = $"Downloading Pinyon Shift {update.Version}: {fraction:P0}");
            AppendLog($"Downloading {update.AssetName} {update.Version} from {update.AssetUrl}");
            var download = await LauncherUpdate.DownloadAsync(client, update, staging, progress, _cancel.Token);
            AppendLog($"SHA-256 matches the release: {update.Sha256}");
            StatusText.Text = "Installing the new launcher…";
            var unpacked = await LauncherUpdate.UnpackAsync(download, staging, _cancel.Token);
            LauncherUpdate.Swap(LauncherUpdate.Plan(unpacked, installed));
            LauncherUpdate.Restart(installed, Environment.GetCommandLineArgs()[1..], CurrentReleaseVersion());
            (Avalonia.Application.Current?.ApplicationLifetime as IClassicDesktopStyleApplicationLifetime)?.Shutdown();
        }
        catch (Exception error)
        {
            try { if (Directory.Exists(staging)) Directory.Delete(staging, recursive: true); }
            catch (Exception cleanup) when (cleanup is IOException or UnauthorizedAccessException) { }
            AppendLog($"Update failed: {error.Message}");
            StatusText.Text = $"The update did not finish; this launcher is unchanged. {error.Message}";
            UpdateButton.IsEnabled = true;
            UpdateButton.Content = $"Update to {update.Version}";
            _updateConfirming = false;
            ShowMode(_mode);
        }
    }
}
