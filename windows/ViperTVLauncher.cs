using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class ViperTVLauncher
{
    [STAThread]
    private static void Main(string[] args)
    {
        try
        {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string pythonw = Path.Combine(root, "runtime", "pythonw.exe");
            string launcher = Path.Combine(root, "windows", "launcher.pyw");
            if (!File.Exists(pythonw) || !File.Exists(launcher))
            {
                MessageBox.Show(
                    "The bundled ViperTV runtime is missing. Please use the complete Windows Standalone release package.",
                    "ViperTV", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }

            string action = args.Length > 0 ? args[0] : "start";
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = pythonw;
            psi.Arguments = Quote(launcher) + " " + Quote(action);
            psi.WorkingDirectory = root;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show(ex.Message, "ViperTV", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private static string Quote(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }
}
