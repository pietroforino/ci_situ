import pygame
import math
import time
from rd03d import RD03D
import sys

class GameSettings:
    def __init__(self):
        # Radar settings
        self.min_play_distance = 1000  # mm - closest detection range
        self.max_play_distance = 2500  # mm - farthest detection range
        self.player_smoothing = 0    # 0-1, higher = more smoothing
        
        # Game physics
        self.puck_speed_multiplier = 0.7
        self.puck_friction = 0.999
        self.paddle_size = 40
        self.puck_size = 15
        
        # AI settings
        self.ai_max_speed = 4.0        # Maximum pixels per frame AI can move
        self.ai_reaction_delay = 0.05   # Seconds of delay for AI reactions
        self.ai_prediction_factor = 0.6 # How well AI predicts puck movement
        
        # Display
        self.window_width = 500
        self.window_height = 1000
        self.fps = 60

class Vector2:
    def __init__(self, x=0, y=0):
        self.x = x
        self.y = y
    
    def length(self):
        return math.sqrt(self.x * self.x + self.y * self.y)
    
    def normalize(self):
        length = self.length()
        if length > 0:
            self.x /= length
            self.y /= length
        return self
    
    def __add__(self, other):
        return Vector2(self.x + other.x, self.y + other.y)
    
    def __sub__(self, other):
        return Vector2(self.x - other.x, self.y - other.y)
    
    def __mul__(self, scalar):
        return Vector2(self.x * scalar, self.y * scalar)

class Paddle:
    def __init__(self, x, y, color, size):
        self.pos = Vector2(x, y)
        self.color = color
        self.size = size
        self.velocity = Vector2(0, 0)
        self.prev_pos = Vector2(x, y)
    
    def update_velocity(self):
        self.velocity = self.pos - self.prev_pos
        self.prev_pos = Vector2(self.pos.x, self.pos.y)
    
    def draw(self, screen):
        pygame.draw.circle(screen, self.color, (int(self.pos.x), int(self.pos.y)), self.size)
        # Draw a smaller inner circle for visual effect
        pygame.draw.circle(screen, (255, 255, 255), (int(self.pos.x), int(self.pos.y)), self.size - 5, 2)

class Puck:
    def __init__(self, x, y, size):
        self.pos = Vector2(x, y)
        self.velocity = Vector2(0, 0.2)
        self.size = size
        self.trail = []  # For visual trail effect
        self.trail_update_counter = 0  # Optimize trail updates
    
    def update(self, settings, paddles, screen_width, screen_height):
        # Update position
        self.pos.x += self.velocity.x * settings.puck_speed_multiplier
        self.pos.y += self.velocity.y * settings.puck_speed_multiplier
        
        # Apply friction
        self.velocity.x *= settings.puck_friction
        self.velocity.y *= settings.puck_friction
        
        # Bounce off walls (left and right walls)
        if self.pos.x <= self.size:
            self.velocity.x = abs(self.velocity.x) * 0.8
            self.pos.x = self.size
        elif self.pos.x >= screen_width - self.size:
            self.velocity.x = -abs(self.velocity.x) * 0.8
            self.pos.x = screen_width - self.size
        
        # Goals (top and bottom)
        goal_width = 200
        goal_x = (screen_width - goal_width) // 2

        # Check top goal
        if self.pos.y <= self.size:
            if goal_x <= self.pos.x <= goal_x + goal_width:
                return "player"  # Player scores
            else:
                self.velocity.y = abs(self.velocity.y) * 0.8  # Bounce
                self.pos.y = self.size

        # Check bottom goal
        elif self.pos.y >= screen_height - self.size:
            if goal_x <= self.pos.x <= goal_x + goal_width:
                return "ai"  # AI scores
            else:
                self.velocity.y = -abs(self.velocity.y) * 0.8  # Bounce
                self.pos.y = screen_height - self.size


        
        # Paddle collisions (optimized)
        for paddle in paddles:
            dx = self.pos.x - paddle.pos.x
            dy = self.pos.y - paddle.pos.y
            distance_sq = dx * dx + dy * dy
            min_distance = self.size + paddle.size
            
            if distance_sq < min_distance * min_distance:
                distance = math.sqrt(distance_sq)
                if distance > 0:
                    # Normalize collision direction
                    nx = dx / distance
                    ny = dy / distance
                    
                    # Separate puck from paddle
                    overlap = min_distance - distance
                    self.pos.x += nx * overlap
                    self.pos.y += ny * overlap
                    
                    # Reflect velocity
                    dot_product = self.velocity.x * nx + self.velocity.y * ny
                    self.velocity.x -= 2 * dot_product * nx
                    self.velocity.y -= 2 * dot_product * ny
                    
                    # Add paddle momentum (simplified)
                    self.velocity.x += paddle.velocity.x * 0.3
                    self.velocity.y += paddle.velocity.y * 0.3
                    
                    # Ensure minimum speed
                    speed = math.sqrt(self.velocity.x * self.velocity.x + self.velocity.y * self.velocity.y)
                    if speed < 2:
                        self.velocity.x = nx * 3
                        self.velocity.y = ny * 3
        
        # Update trail less frequently for performance
        self.trail_update_counter += 1
        if self.trail_update_counter % 3 == 0:  # Update every 3rd frame
            self.trail.append((int(self.pos.x), int(self.pos.y)))
            if len(self.trail) > 8:  # Shorter trail
                self.trail.pop(0)
        
                # Anti-stuck: gently pull puck downward toward center goal if stuck behind AI
        goal_center_x = screen_width / 2
        if self.pos.y < screen_height * 0.1:
            pull_strength = 0.1
            self.velocity.x += (goal_center_x - self.pos.x) * pull_strength * 0.001
            self.velocity.y += 0.3  # Small downward nudge

        
        return None
    
    def reset(self, x, y):
        self.pos = Vector2(x, y)
        # Start puck moving slowly toward player (positive Y direction)
        self.velocity = Vector2(0, 2)  # Moving down toward player
        self.trail = []
    
    def draw(self, screen):
        # Draw simplified trail for performance
        if len(self.trail) > 1:
            for i in range(1, len(self.trail)):
                alpha = i / len(self.trail)
                color = (int(255 * alpha), int(100 * alpha), int(100 * alpha))
                radius = max(2, int(self.size * alpha * 0.5))
                pygame.draw.circle(screen, color, self.trail[i], radius)
        
        # Draw puck
        pygame.draw.circle(screen, (255, 200, 200), (int(self.pos.x), int(self.pos.y)), self.size)
        pygame.draw.circle(screen, (255, 255, 255), (int(self.pos.x), int(self.pos.y)), self.size - 3, 2)

class AIPlayer:
    def __init__(self, paddle, settings):
        self.paddle = paddle
        self.settings = settings
        self.target_pos = Vector2(paddle.pos.x, paddle.pos.y)
        self.last_reaction_time = 0
    
    def update(self, puck, screen_width, screen_height):
        current_time = time.time()
        
        # Only react after delay
        if current_time - self.last_reaction_time > self.settings.ai_reaction_delay:
            # Predict where puck will be (simplified)
            future_frames = 15
            predicted_x = puck.pos.x + puck.velocity.x * future_frames * self.settings.ai_prediction_factor
            predicted_y = puck.pos.y + puck.velocity.y * future_frames * self.settings.ai_prediction_factor
            
            # Only chase if puck is coming towards AI's side
            if puck.velocity.y > 0 or puck.pos.y < screen_height * 0.4:
                self.target_pos.x = predicted_x
                self.target_pos.y = max(screen_height * 0.1, min(screen_height * 0.45, predicted_y))
            else:
                # Return to center when not actively defending
                self.target_pos.x = screen_width * 0.5
                self.target_pos.y = screen_height * 0.25
            
            self.last_reaction_time = current_time
        
        # Move towards target with speed limit (optimized)
        dx = self.target_pos.x - self.paddle.pos.x
        dy = self.target_pos.y - self.paddle.pos.y
        distance = math.sqrt(dx * dx + dy * dy)
        
        if distance > 0:
            move_distance = min(self.settings.ai_max_speed, distance)
            self.paddle.pos.x += (dx / distance) * move_distance
            self.paddle.pos.y += (dy / distance) * move_distance
        
        # Keep AI paddle in bounds
        self.paddle.pos.x = max(self.paddle.size, min(screen_width - self.paddle.size, self.paddle.pos.x))
        self.paddle.pos.y = max(self.paddle.size, min(screen_height * 0.5 - self.paddle.size, self.paddle.pos.y))
        
        self.paddle.update_velocity()

class RadarAirHockey:
    def __init__(self):
        pygame.init()
        self.settings = GameSettings()
        
        # Initialize display
        self.screen = pygame.display.set_mode((self.settings.window_width, self.settings.window_height))
        pygame.display.set_caption("Radar Air Hockey")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 36)
        self.small_font = pygame.font.Font(None, 24)
        
        # Initialize radar
        try:
            self.radar = RD03D()
            self.radar_connected = True
            print("Radar connected successfully!")
        except Exception as e:
            print(f"Could not connect to radar: {e}")
            print("Running in demo mode - use mouse to control paddle")
            self.radar_connected = False
        
        # Game objects
        self.player_paddle = Paddle(
            self.settings.window_width // 2, 
            self.settings.window_height - 80, 
            (100, 150, 255), 
            self.settings.paddle_size
        )
        
        self.ai_paddle = Paddle(
            self.settings.window_width // 2, 
            80, 
            (255, 100, 100), 
            self.settings.paddle_size
        )
        
        self.puck = Puck(
            self.settings.window_width // 2, 
            self.settings.window_height // 2, 
            self.settings.puck_size
        )
        
        self.ai_player = AIPlayer(self.ai_paddle, self.settings)
        
        # Game state
        self.player_score = 0
        self.ai_score = 0
        self.game_paused = False
        self.show_settings = False
        
        # Player position smoothing
        self.smoothed_player_pos = Vector2(self.player_paddle.pos.x, self.player_paddle.pos.y)
    
    def get_radar_position(self):
        """Get position from radar sensor"""
        if not self.radar_connected:
            # Demo mode - use mouse
            mouse_pos = pygame.mouse.get_pos()
            return mouse_pos[0], mouse_pos[1]
        
        try:
            if self.radar.update():
                target = self.radar.get_target(1)
                if target and target.distance > 0:
                    # Map radar distance/angle to screen coordinates
                    distance = target.distance  # mm
                    angle = math.radians(target.angle)  # Convert to radians
                    
                    # Map distance to Y coordinate (FIXED: farther = bottom of screen)
                    if self.settings.min_play_distance <= distance <= self.settings.max_play_distance:
                        # Normalize distance to 0-1 range
                        normalized_distance = (distance - self.settings.min_play_distance) / \
                                            (self.settings.max_play_distance - self.settings.min_play_distance)
                        
                        # Map to player's half of screen (farther distance = bottom of screen)
                        y = self.settings.window_height * 0.6 + (normalized_distance * self.settings.window_height * 0.35)
                        
                        # Map angle to X coordinate (FIXED: flip the direction)
                        # Assuming -60° to +60° maps to screen width
                        normalized_angle = (angle + math.radians(60)) / math.radians(120)
                        x = self.settings.window_width - (normalized_angle * self.settings.window_width)
                        
                        # Clamp to screen bounds
                        x = max(self.settings.paddle_size, min(self.settings.window_width - self.settings.paddle_size, x))
                        y = max(self.settings.window_height * 0.5, min(self.settings.window_height - self.settings.paddle_size, y))
                        
                        return x, y
        except Exception as e:
            print(f"Radar error: {e}")
        
        return None, None
    
    def update_player_position(self):
        """Update player paddle position with smoothing"""
        x, y = self.get_radar_position()
        
        if x is not None and y is not None:
            target_pos = Vector2(x, y)
            
            # Apply smoothing
            self.smoothed_player_pos = self.smoothed_player_pos * self.settings.player_smoothing + \
                                     target_pos * (1 - self.settings.player_smoothing)
            
            self.player_paddle.pos = Vector2(self.smoothed_player_pos.x, self.smoothed_player_pos.y)
            self.player_paddle.update_velocity()
    
    def draw_field(self):
        """Draw the air hockey field"""
        # Background
        self.screen.fill((20, 40, 60))
        
        # Center line
        pygame.draw.line(self.screen, (100, 100, 100), 
                        (0, self.settings.window_height // 2), 
                        (self.settings.window_width, self.settings.window_height // 2), 3)
        
        # Goals
        goal_width = 200
        goal_x = (self.settings.window_width - goal_width) // 2
        
        # Player goal (bottom)
        pygame.draw.rect(self.screen, (100, 255, 100), 
                        (goal_x, self.settings.window_height - 10, goal_width, 10))
        
        # AI goal (top)
        pygame.draw.rect(self.screen, (255, 100, 100), 
                        (goal_x, 0, goal_width, 10))
        
        # Corner arcs
        arc_radius = 50
        pygame.draw.arc(self.screen, (100, 100, 100), 
                       (0, 0, arc_radius * 2, arc_radius * 2), 0, math.pi/2, 2)
        pygame.draw.arc(self.screen, (100, 100, 100), 
                       (self.settings.window_width - arc_radius * 2, 0, arc_radius * 2, arc_radius * 2), 
                       math.pi/2, math.pi, 2)
    
    def draw_ui(self):
        """Draw user interface elements"""
        # Score
        score_text = self.font.render(f"Player: {self.player_score}  AI: {self.ai_score}", 
                                     True, (255, 255, 255))
        self.screen.blit(score_text, (10, 10))
        
        # Instructions
        if not self.radar_connected:
            demo_text = self.small_font.render("DEMO MODE - Use mouse to control paddle", 
                                             True, (255, 255, 100))
            self.screen.blit(demo_text, (10, self.settings.window_height - 30))
        
        # Controls
        controls = [
            "SPACE: Pause/Resume",
            "S: Settings",
            "R: Reset Game",
            "ESC: Quit"
        ]
        
        for i, control in enumerate(controls):
            text = self.small_font.render(control, True, (200, 200, 200))
            self.screen.blit(text, (self.settings.window_width - 150, 10 + i * 20))
    
    def draw_settings(self):
        """Draw settings overlay"""
        overlay = pygame.Surface((self.settings.window_width, self.settings.window_height))
        overlay.set_alpha(200)
        overlay.fill((0, 0, 0))
        self.screen.blit(overlay, (0, 0))
        
        settings_text = [
            "SETTINGS",
            "",
            f"Min Distance: {self.settings.min_play_distance}mm [1/2]",
            f"Max Distance: {self.settings.max_play_distance}mm [3/4]",
            f"Player Smoothing: {self.settings.player_smoothing:.1f} [Q/W]",
            f"Puck Speed: {self.settings.puck_speed_multiplier:.1f} [A/S]",
            f"AI Max Speed: {self.settings.ai_max_speed:.1f} [Z/X]",
            f"AI Reaction: {self.settings.ai_reaction_delay:.2f}s [C/V]",
            "",
            "Press S again to close settings"
        ]
        
        y_offset = 100
        for text in settings_text:
            if text == "SETTINGS":
                rendered = self.font.render(text, True, (255, 255, 100))
            elif text == "":
                y_offset += 10
                continue
            else:
                rendered = self.small_font.render(text, True, (255, 255, 255))
            
            self.screen.blit(rendered, (50, y_offset))
            y_offset += 30
    
    def handle_settings_input(self, key):
        """Handle settings adjustment input"""
        if key == pygame.K_1:
            self.settings.min_play_distance = max(500, self.settings.min_play_distance - 200)
        elif key == pygame.K_2:
            self.settings.min_play_distance = min(3000, self.settings.min_play_distance + 200)
        elif key == pygame.K_3:
            self.settings.max_play_distance = max(self.settings.min_play_distance + 500, 
                                                self.settings.max_play_distance - 200)
        elif key == pygame.K_4:
            self.settings.max_play_distance = min(6000, self.settings.max_play_distance + 200)
        elif key == pygame.K_q:
            self.settings.player_smoothing = max(0.1, self.settings.player_smoothing - 0.1)
        elif key == pygame.K_w:
            self.settings.player_smoothing = min(0.9, self.settings.player_smoothing + 0.1)
        elif key == pygame.K_a:
            self.settings.puck_speed_multiplier = max(0.5, self.settings.puck_speed_multiplier - 0.1)
        elif key == pygame.K_s and not self.show_settings:
            self.settings.puck_speed_multiplier = min(2.0, self.settings.puck_speed_multiplier + 0.1)
        elif key == pygame.K_z:
            self.settings.ai_max_speed = max(2.0, self.settings.ai_max_speed - 0.5)
        elif key == pygame.K_x:
            self.settings.ai_max_speed = min(15.0, self.settings.ai_max_speed + 0.5)
        elif key == pygame.K_c:
            self.settings.ai_reaction_delay = max(0.01, self.settings.ai_reaction_delay - 0.01)
        elif key == pygame.K_v:
            self.settings.ai_reaction_delay = min(0.2, self.settings.ai_reaction_delay + 0.01)
    
    def reset_game(self):
        """Reset the game state"""
        self.player_score = 0
        self.ai_score = 0
        self.puck.reset(self.settings.window_width // 2, self.settings.window_height // 2)
        self.game_paused = False
    
    def run(self):
        """Main game loop"""
        running = True
        
        while running:
            # Handle events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_SPACE:
                        self.game_paused = not self.game_paused
                    elif event.key == pygame.K_r:
                        self.reset_game()
                    elif event.key == pygame.K_s:
                        if self.show_settings:
                            self.show_settings = False
                        else:
                            self.show_settings = True
                            self.game_paused = True
                    
                    if self.show_settings:
                        self.handle_settings_input(event.key)
            
            if not self.game_paused and not self.show_settings:
                # Update player position
                self.update_player_position()
                
                # Update AI
                self.ai_player.update(self.puck, self.settings.window_width, self.settings.window_height)
                
                # Update puck
                goal_scored = self.puck.update(self.settings, [self.player_paddle, self.ai_paddle], 
                                             self.settings.window_width, self.settings.window_height)
                
                # Handle scoring
                if goal_scored == "player":
                    self.player_score += 1
                    self.puck.reset(self.settings.window_width // 2, self.settings.window_height // 2)
                    time.sleep(1)  # Brief pause after goal
                elif goal_scored == "ai":
                    self.ai_score += 1
                    self.puck.reset(self.settings.window_width // 2, self.settings.window_height // 2)
                    time.sleep(1)  # Brief pause after goal
            
            # Draw everything
            self.draw_field()
            self.player_paddle.draw(self.screen)
            self.ai_paddle.draw(self.screen)
            self.puck.draw(self.screen)
            self.draw_ui()
            
            if self.show_settings:
                self.draw_settings()
            
            if self.game_paused and not self.show_settings:
                pause_text = self.font.render("PAUSED - Press SPACE to resume", True, (255, 255, 100))
                text_rect = pause_text.get_rect(center=(self.settings.window_width//2, self.settings.window_height//2))
                self.screen.blit(pause_text, text_rect)
            
            pygame.display.flip()
            self.clock.tick(self.settings.fps)
        
        # Cleanup
        if self.radar_connected:
            self.radar.close()
        pygame.quit()
        sys.exit()

if __name__ == "__main__":
    game = RadarAirHockey()
    game.run()