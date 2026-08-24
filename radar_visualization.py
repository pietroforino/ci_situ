import pygame
import math
import time
from rd03d import RD03D

class RadarDisplay:
    def __init__(self, width=1200, height=900):
        pygame.init()
        self.width = width
        self.height = height
        self.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption("mmWave Radar Display")
        
        # Colors
        self.BLACK = (0, 0, 0)
        self.GREEN = (0, 255, 0)
        self.DARK_GREEN = (0, 100, 0)
        self.BRIGHT_GREEN = (0, 255, 100)
        self.RED = (255, 0, 0)
        self.YELLOW = (255, 255, 0)
        self.WHITE = (255, 255, 255)
        self.GRAY = (128, 128, 128)
        
        # Radar settings
        self.info_panel_width = 200  # Reserve space for info panel
        self.radar_area_width = width - self.info_panel_width - 40  # Leave some margin
        self.radar_area_height = height - 100  # Leave space for title and margin
        
        # Calculate radar position and size to maximize use of available space
        self.center_x = self.info_panel_width + self.radar_area_width // 2
        self.center_y = height - 80  # Position near bottom with margin
        
        # Radar radius should use most of the available space
        max_radius_by_width = self.radar_area_width // 2 - 20
        max_radius_by_height = self.radar_area_height - 60  # Account for radar being at bottom
        self.radar_radius = min(max_radius_by_width, max_radius_by_height)
        
        self.max_range = 7000  # 7 meters in mm (adjustable)
        self.fov_angle = 120  # 120 degree field of view
        
        # Font for text
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 18)
        
        # Sweep animation
        self.sweep_angle = 0
        self.sweep_speed = 2
        
    def set_max_range(self, range_meters):
        """Set the maximum range in meters"""
        self.max_range = range_meters * 1000
        
    def distance_to_pixels(self, distance_mm):
        """Convert distance in mm to pixel radius"""
        return int((distance_mm / self.max_range) * self.radar_radius)
    
    def angle_to_screen_angle(self, angle_deg):
        """Convert radar angle to screen angle (radar faces up)"""
        # Radar coordinate: 0° is straight ahead (up), positive is right
        # Screen coordinate: 0° is right, positive is clockwise
        return -angle_deg + 90
    
    def polar_to_cartesian(self, distance_mm, angle_deg):
        """Convert polar coordinates to screen cartesian"""
        pixel_radius = self.distance_to_pixels(distance_mm)
        screen_angle = math.radians(self.angle_to_screen_angle(angle_deg))
        
        x = self.center_x + pixel_radius * math.cos(screen_angle)
        y = self.center_y - pixel_radius * math.sin(screen_angle)
        
        return int(x), int(y)
    
    def draw_range_arc(self, radius, start_angle, end_angle, color, width=1):
        """Draw an arc for range circles within the FOV"""
        if radius <= 0 or radius > self.radar_radius:
            return
            
        # Convert angles to screen coordinates
        start_screen_angle = math.radians(self.angle_to_screen_angle(start_angle))
        end_screen_angle = math.radians(self.angle_to_screen_angle(end_angle))
        
        # Create points for the arc
        points = []
        angle_step = (end_screen_angle - start_screen_angle) / 50  # 50 segments for smooth arc
        
        for i in range(51):  # 51 points for 50 segments
            angle = start_screen_angle + i * angle_step
            x = self.center_x + radius * math.cos(angle)
            y = self.center_y - radius * math.sin(angle)
            points.append((x, y))
        
        # Draw the arc as connected line segments
        if len(points) > 1:
            pygame.draw.lines(self.screen, color, False, points, width)
    
    def draw_radar_background(self):
        """Draw the radar display background"""
        # Fill background
        self.screen.fill(self.BLACK)
        
        # Draw range circles/arcs only within FOV
        fov_half = self.fov_angle / 2
        max_range_meters = self.max_range / 1000
        
        # Dynamic range intervals based on max range
        if max_range_meters <= 5:
            range_intervals = list(range(1, int(max_range_meters) + 1))
        elif max_range_meters <= 10:
            range_intervals = list(range(2, int(max_range_meters) + 1, 2))
        else:
            range_intervals = list(range(5, int(max_range_meters) + 1, 5))
        
        for range_m in range_intervals:
            range_mm = range_m * 1000
            radius = self.distance_to_pixels(range_mm)
            if 0 < radius <= self.radar_radius:
                # Draw arc only within FOV
                self.draw_range_arc(radius, -fov_half, fov_half, self.DARK_GREEN)
                
                # Range labels - position them better
                label_angle = 0  # Put label at center of FOV
                screen_angle = math.radians(self.angle_to_screen_angle(label_angle))
                label_x = self.center_x + (radius + 15) * math.cos(screen_angle)
                label_y = self.center_y - (radius + 15) * math.sin(screen_angle)
                
                label = self.small_font.render(f"{range_m}m", True, self.DARK_GREEN)
                label_rect = label.get_rect(center=(label_x, label_y))
                self.screen.blit(label, label_rect)
        
        # Draw field of view boundary lines
        for angle in [-fov_half, fov_half]:
            screen_angle = math.radians(self.angle_to_screen_angle(angle))
            end_x = self.center_x + self.radar_radius * math.cos(screen_angle)
            end_y = self.center_y - self.radar_radius * math.sin(screen_angle)
            pygame.draw.line(self.screen, self.GREEN, 
                           (self.center_x, self.center_y), (end_x, end_y), 2)
        
        # Draw angle lines every 30 degrees within FOV
        for angle in range(-60, 61, 30):
            if abs(angle) <= fov_half and angle != 0:
                screen_angle = math.radians(self.angle_to_screen_angle(angle))
                end_x = self.center_x + self.radar_radius * math.cos(screen_angle)
                end_y = self.center_y - self.radar_radius * math.sin(screen_angle)
                pygame.draw.line(self.screen, self.DARK_GREEN, 
                               (self.center_x, self.center_y), (end_x, end_y), 1)
                
                # Angle labels
                label_x = self.center_x + (self.radar_radius + 25) * math.cos(screen_angle)
                label_y = self.center_y - (self.radar_radius + 25) * math.sin(screen_angle)
                label = self.small_font.render(f"{angle}°", True, self.DARK_GREEN)
                label_rect = label.get_rect(center=(label_x, label_y))
                self.screen.blit(label, label_rect)
        
        # Draw center line (0 degrees)
        screen_angle = math.radians(self.angle_to_screen_angle(0))
        end_x = self.center_x + self.radar_radius * math.cos(screen_angle)
        end_y = self.center_y - self.radar_radius * math.sin(screen_angle)
        pygame.draw.line(self.screen, self.GREEN, 
                       (self.center_x, self.center_y), (end_x, end_y), 1)
        
        # Draw center point
        pygame.draw.circle(self.screen, self.GREEN, (self.center_x, self.center_y), 4)
        
        # Draw radar area outline
        fov_half_rad = math.radians(fov_half)
        left_angle = math.radians(self.angle_to_screen_angle(-fov_half))
        right_angle = math.radians(self.angle_to_screen_angle(fov_half))
        
        # Create arc points for the outer boundary
        arc_points = [(self.center_x, self.center_y)]
        for i in range(51):
            angle = left_angle + i * (right_angle - left_angle) / 50
            x = self.center_x + self.radar_radius * math.cos(angle)
            y = self.center_y - self.radar_radius * math.sin(angle)
            arc_points.append((x, y))
        arc_points.append((self.center_x, self.center_y))
        
        pygame.draw.polygon(self.screen, self.DARK_GREEN, arc_points, 1)
    
    def draw_sweep(self):
        """Draw rotating sweep line"""
        fov_half = self.fov_angle / 2
        if abs(self.sweep_angle) <= fov_half:
            screen_angle = math.radians(self.angle_to_screen_angle(self.sweep_angle))
            end_x = self.center_x + self.radar_radius * math.cos(screen_angle)
            end_y = self.center_y - self.radar_radius * math.sin(screen_angle)
            
            # Draw sweep line with fade effect
            for i in range(5):
                alpha_angle = self.sweep_angle - i * 3
                if abs(alpha_angle) <= fov_half:
                    alpha_screen_angle = math.radians(self.angle_to_screen_angle(alpha_angle))
                    alpha_end_x = self.center_x + self.radar_radius * math.cos(alpha_screen_angle)
                    alpha_end_y = self.center_y - self.radar_radius * math.sin(alpha_screen_angle)
                    
                    color_intensity = 255 - (i * 40)
                    if color_intensity > 0:
                        color = (0, color_intensity, 0)
                        pygame.draw.line(self.screen, color, 
                                       (self.center_x, self.center_y), 
                                       (alpha_end_x, alpha_end_y), max(1, 3-i))
        
        # Update sweep angle
        self.sweep_angle += self.sweep_speed
        if self.sweep_angle > fov_half:
            self.sweep_angle = -fov_half
    
    def draw_target(self, target, target_num):
        """Draw a target with speed arrow"""
        if target.distance > self.max_range:
            return  # Target too far
        
        # Check if target is within field of view
        if abs(target.angle) > self.fov_angle / 2:
            return
        
        x, y = self.polar_to_cartesian(target.distance, target.angle)
        
        # Target colors based on number
        colors = [self.BRIGHT_GREEN, self.YELLOW, self.RED]
        color = colors[target_num % len(colors)]
        
        # Draw target dot
        pygame.draw.circle(self.screen, color, (x, y), 8)
        pygame.draw.circle(self.screen, self.WHITE, (x, y), 8, 2)
        
        # Draw speed arrow (speed is radial - toward or away from sensor)
        if abs(target.speed) > 1:  # Only draw if speed is significant
            # Arrow length proportional to speed (max 40 pixels)
            arrow_length = min(40, abs(target.speed) * 2)
            
            # Speed direction: positive = away from sensor, negative = toward sensor
            angle_rad = math.radians(self.angle_to_screen_angle(target.angle))
            
            if target.speed > 0:  # Moving away
                arrow_end_x = x + arrow_length * math.cos(angle_rad)
                arrow_end_y = y - arrow_length * math.sin(angle_rad)
                arrow_color = self.RED
            else:  # Moving toward
                arrow_end_x = x - arrow_length * math.cos(angle_rad)
                arrow_end_y = y + arrow_length * math.sin(angle_rad)
                arrow_color = self.GREEN
            
            # Draw arrow line
            pygame.draw.line(self.screen, arrow_color, (x, y), (arrow_end_x, arrow_end_y), 3)
            
            # Draw arrow head
            arrow_angle = math.atan2(arrow_end_y - y, arrow_end_x - x)
            head_length = 10
            head1_x = arrow_end_x - head_length * math.cos(arrow_angle - 0.5)
            head1_y = arrow_end_y - head_length * math.sin(arrow_angle - 0.5)
            head2_x = arrow_end_x - head_length * math.cos(arrow_angle + 0.5)
            head2_y = arrow_end_y - head_length * math.sin(arrow_angle + 0.5)
            
            pygame.draw.polygon(self.screen, arrow_color, 
                              [(arrow_end_x, arrow_end_y), (head1_x, head1_y), (head2_x, head2_y)])
        
        # Target label
        label_text = f"T{target_num+1}"
        label = self.small_font.render(label_text, True, color)
        self.screen.blit(label, (x + 12, y - 12))
    
    def draw_info_panel(self, targets):
        """Draw information panel"""
        panel_x = 10
        panel_y = 10
        
        # Draw panel background
        panel_rect = pygame.Rect(5, 5, self.info_panel_width - 10, self.height - 10)
        pygame.draw.rect(self.screen, (20, 20, 20), panel_rect)
        pygame.draw.rect(self.screen, self.DARK_GREEN, panel_rect, 2)
        
        # Title
        title = self.font.render("mmWave Radar", True, self.WHITE)
        self.screen.blit(title, (panel_x, panel_y))
        
        # Range info
        range_text = self.small_font.render(f"Max Range: {self.max_range/1000:.1f}m", True, self.GRAY)
        self.screen.blit(range_text, (panel_x, panel_y + 30))
        
        # Target info
        y_offset = 60
        active_targets = 0
        for i, target in enumerate(targets[:3]):  # Max 3 targets
            if target and target.distance <= self.max_range and abs(target.angle) <= 60:
                active_targets += 1
                color = [self.BRIGHT_GREEN, self.YELLOW, self.RED][i]
                
                info_lines = [
                    f"Target {i+1}:",
                    f"  Distance: {target.distance:.0f}mm",
                    f"  Angle: {target.angle:.1f}°",
                    f"  Speed: {target.speed:.1f}cm/s, {'(away)' if target.speed > 0 else '(toward)' if target.speed < 0 else '(still)'}",
                ]
                
                for j, line in enumerate(info_lines):
                    text_color = color if j == 0 else self.WHITE
                    text = self.small_font.render(line, True, text_color)
                    self.screen.blit(text, (panel_x, panel_y + y_offset + j * 18))
                
                y_offset += 120
        
        if active_targets == 0:
            no_targets = self.small_font.render("No targets detected", True, self.GRAY)
            self.screen.blit(no_targets, (panel_x, panel_y + y_offset))
        
        # Legend
        legend_y = self.height - 140
        legend_title = self.small_font.render("Speed Legend:", True, self.WHITE)
        self.screen.blit(legend_title, (panel_x, legend_y))
        
        # Speed arrow legend
        pygame.draw.line(self.screen, self.RED, (panel_x, legend_y + 25), (panel_x + 30, legend_y + 25), 3)
        pygame.draw.polygon(self.screen, self.RED, [(panel_x + 30, legend_y + 25), 
                                                   (panel_x + 25, legend_y + 20), 
                                                   (panel_x + 25, legend_y + 30)])
        away_text = self.small_font.render("Moving Away", True, self.WHITE)
        self.screen.blit(away_text, (panel_x + 40, legend_y + 20))
        
        pygame.draw.line(self.screen, self.GREEN, (panel_x, legend_y + 45), (panel_x + 30, legend_y + 45), 3)
        pygame.draw.polygon(self.screen, self.GREEN, [(panel_x, legend_y + 45), 
                                                     (panel_x + 5, legend_y + 40), 
                                                     (panel_x + 5, legend_y + 50)])
        toward_text = self.small_font.render("Moving Toward", True, self.WHITE)
        self.screen.blit(toward_text, (panel_x + 40, legend_y + 40))

def main():
    # Initialize radar
    radar = RD03D()
    radar.set_multi_mode(True)
    
    # Initialize display with larger window to test scaling
    display = RadarDisplay(1200, 800)  # Larger window
    display.set_max_range(7)  # Set to 7 meters
    
    clock = pygame.time.Clock()
    
    print("Radar visualization started. Close window to exit.")
    print(f"Max range: {display.max_range/1000}m")
    print(f"Radar radius: {display.radar_radius} pixels")
    
    try:
        running = True
        while running:
            # Handle events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
            
            # Update radar data
            radar.update()
            targets = [radar.get_target(1), radar.get_target(2), radar.get_target(3)]
            
            # Draw everything
            display.draw_radar_background()
            display.draw_sweep()
            
            # Draw targets
            for i, target in enumerate(targets):
                if target:
                    display.draw_target(target, i)
            
            display.draw_info_panel(targets)
            
            # Update display
            pygame.display.flip()
            clock.tick(30)  # 30 FPS
    
    except KeyboardInterrupt:
        pass
    finally:
        radar.close()
        pygame.quit()
        print("Radar visualization stopped.")

if __name__ == "__main__":
    main()