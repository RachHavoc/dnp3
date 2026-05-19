# MITRE Caldera™ for OT plugin: plugin: DNP3

A [MITRE Caldera™ for OT](https://github.com/mitre/caldera-ot) plugin supplying [Caldera](https://github.com/mitre/caldera) with DNP3 protocol TTPs mapped to MITRE ATT&CK® for ICS [v14](https://attack.mitre.org/resources/updates/updates-october-2023/). This is part of a series of plugins that provide added threat emulation capability for Operational Technology (OT) environments. 

Full DNP3 plugin [documentation](docs/dnp3.md) can be viewed as part of fieldmanual, once the Caldera server is running. 

## Installation

To run Caldera along with DNP3 plugin:
1. Download Caldera as detailed in the [Installation Guide](https://github.com/mitre/caldera)
2. Install the dnp3 plugin in Caldera's plugin directory: `caldera/plugins`
3. Enable the dnp3 plugin by adding `- dnp3` to the list of enabled plugins in `conf/local.yml` or `conf/default.yml` (if running Caldera in insecure mode)

### Caldera Version
This plugin is compatible with Caldera v4.2.0 and v5.0.0. The latest version of Caldera can be checked out using the following method:
```
git clone --recursive https://github.com/mitre/caldera.git
```

## Usage
1. Install and enable the plugin as described [above](#installation).
2. Optionally, create a fact source to store attributes of the target system. An example is provided [here](./data/sources/531c81f1-51d7-427f-ba0a-3faf0fd509b3.yml).
3. Start the Caldera server
4. Create a new Operation, optionally using the fact source from step 2.
5. Use "Add Potential Link" to run a specific ability from this plugin. Fact values can can be entered manually, or selected from a fact source.

## DNP3 Substation Attack Scenario

This plugin includes an adversary profile (`data/adversaries/dnp3_substation_adversary.yml`) emulating TTPs against internet-exposed DNP3 outstations, based on the CISA April 2026 advisory. It sequences the full ICS kill chain across five phases:

1. **Discovery** — port scan → device attribute fingerprinting (vendor, firmware, serial)
2. **Collection** — integrity poll → analog input reads → binary input reads → event buffer drain
3. **Inhibit Response** — disable unsolicited responses (blinds the SCADA master station)
4. **Impair Process Control** — direct operate binary output (breaker trip) → analog setpoint manipulation
5. **Impact** — cold restart

A scenario-specific fact source is provided at `data/sources/dnp3_substation_scenario.yml` with default values for a substation exercise range.

### Testing with the DNP3 Outstation Simulator

The `dnp3-outstation` binary included in this plugin can be used to stand up a simulated DNP3 device for testing without access to real hardware. Run it manually on the target machine before starting an operation:

**Linux:**
```bash
chmod +x dnp3-outstation
./dnp3-outstation --ip 0.0.0.0 --port 20000 --local 10 --remote 1
```

**macOS:**
```bash
chmod +x dnp3-outstation_darwin
./dnp3-outstation_darwin --ip 0.0.0.0 --port 20000 --local 10 --remote 1
```

**Windows:**
```cmd
.\dnp3-outstation.exe --ip 0.0.0.0 --port 20000 --local 10 --remote 1
```

Adjust `--local` and `--remote` to match the `dnp3.local.link` and `dnp3.remote.link` values in your fact source. Once running, point the attacker agent at the simulator's IP and run the adversary profile.
