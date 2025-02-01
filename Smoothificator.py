# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
#
# Copyright (c) [2025] [Roman Tenger]
import re
import sys
import logging
import os
import argparse

# Get the directory where the script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# Configure logging
log_file_path = os.path.join(script_dir, "smooth_wall_log.txt")
logging.basicConfig(
    filename=log_file_path,
    filemode="w",
    level=logging.INFO,
    format="%(asctime)s - %(message)s"
)

def get_layer_height(gcode_lines):
    """Extract layer height from G-code header comments"""
    for line in gcode_lines:
        if "layer_height =" in line.lower():
            match = re.search(r'; layer_height = (\d*\.?\d+)', line, re.IGNORECASE)
            if match:
                return float(match.group(1))
    return None

def process_gcode(input_file, outer_layer_height, debug = False):
    current_layer = 0
    current_z = 0.0
    in_external_perimeter = False
    external_block_lines = []
    
    logging.info("Starting G-code processing")
    logging.info(f"Input file: {input_file}")
    logging.info(f"Desired outer wall height: {outer_layer_height}mm")

    # Read the input G-code
    with open(input_file, 'r') as infile:
        lines = infile.readlines()

    # Get base layer height
    base_layer_height = get_layer_height(lines)
    if not base_layer_height:
        logging.error("Could not find layer height in G-code file")
        sys.exit(1)
    
    logging.info(f"Base layer height: {base_layer_height}mm")
    
    # Validate outer layer height
    if outer_layer_height <= 0:
        logging.error(f"Outer layer height ({outer_layer_height}mm) must be greater than 0")
        sys.exit(1)
    
    # Calculate number of passes needed
    passes_needed = round(base_layer_height / outer_layer_height)
    height_per_pass = base_layer_height / passes_needed
    extrusion_multiplier = 1.0 / passes_needed  # Each pass gets an equal portion of the original extrusion
    
    logging.info(f"Number of passes: {passes_needed}")
    logging.info(f"Height per pass: {height_per_pass:.3f}mm")
    logging.info(f"Extrusion multiplier: {extrusion_multiplier:.3f}")

    # Process the G-code
    modified_lines = []
    i = 0
    current_z = 0
    while i < len(lines):
        line = lines[i]
        
        # Detect layer changes
        if line.startswith("G1 Z"):
            z_match = re.search(r'Z([-\d.]+)', line)
            if debug:
                logging.info(f"Z change match in line {i}: {line}")
            if z_match:
                past_z = current_z
                current_z = float(z_match.group(1))
                current_layer += 1
                logging.info(f"Layer {current_layer} detected at Z={current_z:.3f}")
                if (past_z + (base_layer_height * 2) <= current_z):
                    logging.error(f"Z difference was to big:{past_z} and {current_z}")
            modified_lines.append(line)
            i += 1
            continue

        # Start of external perimeter block
        if ";TYPE:External perimeter" in line or ";TYPE:Outer wall" in line:
            if debug:
                logging.info(f"External block in line: {i}")
            external_block_lines = []
            # Collect all lines until next type change or empty line
            while i < len(lines):
                current_line = lines[i]
                if i + 1 < len(lines) and (";TYPE:" in lines[i + 1] or "M" in lines[i + 1] and not "M73" in lines[i + 1]):
                    if debug:
                        logging.info(f"External block stopped in line {i + 1}: {lines[i + 1]}") 
                    external_block_lines.append(current_line)
                    i += 1
                    break
                external_block_lines.append(current_line)
                i += 1

            # Process the collected block
            if external_block_lines:
                # Find the starting position from the last G1 move before the external perimeter block
                start_pos = None
                for j in range(i - len(external_block_lines) - 1, max(0, i - len(external_block_lines) - 10), -1):
                    line = lines[j]
                    if "G1" in line and "X" in line and "Y" in line:
                        x_match = re.search(r'X([-\d.]+)', line)
                        y_match = re.search(r'Y([-\d.]+)', line)
                        if x_match and y_match:
                            start_pos = (float(x_match.group(1)), float(y_match.group(1)))
                            break

                # Generate passes
                for pass_num in range(passes_needed):
                    # Calculate Z height for this pass
                    pass_z = current_z + (pass_num * height_per_pass)
                    
                    # Add travel move back to start position (except for first pass)
                    if pass_num > 0 and start_pos:
                        modified_lines.append(f"G1 X{start_pos[0]:.3f} Y{start_pos[1]:.3f} F9000 ; Travel back to start\n")
                    
                    # Set Z height for this pass
                    modified_lines.append(f"G1 Z{pass_z:.3f} ; Pass {pass_num + 1} of {passes_needed}\n")
                    
                    # Process extrusion lines
                    for block_line in external_block_lines:
                        if "G1" in block_line and "E" in block_line:
                            e_match = re.search(r'E([-\d.]+)', block_line)
                            if e_match:
                                e_value = float(e_match.group(1))
                                new_e_value = e_value * extrusion_multiplier
                                modified_line = re.sub(r'E[-\d.]+', f'E{new_e_value:.5f}', block_line)
                                modified_lines.append(modified_line)
                        else:
                            modified_lines.append(block_line)
        else:
            modified_lines.append(line)
            i += 1

    # Overwrite the input file with the modified G-code
    with open(input_file, 'w') as outfile:
        outfile.writelines(modified_lines)

    logging.info("G-code processing completed")
    logging.info(f"Log file saved at {log_file_path}")

# Main execution
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Process G-code file to modify external perimeter printing.')
    parser.add_argument('input_file', help='Input G-code file')
    parser.add_argument('-outerLayerHeight', '--outer-layer-height', type=float, required=True,
                       help='Desired height for outer walls (mm)')
    parser.add_argument('-dev', '--debug', action=argparse.BooleanOptionalAction,
                       help='Debug code')
    
    args = parser.parse_args()
    
    process_gcode(input_file=args.input_file, outer_layer_height=args.outer_layer_height, debug = args.debug)
