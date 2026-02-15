"""Generate realistic test student applications for agent testing."""

import random
from typing import List, Dict, Any


class TestDataGenerator:
    """Generates realistic synthetic student applications for testing."""
    
    FIRST_NAMES = [
        'Emma', 'Liam', 'Olivia', 'Noah', 'Ava', 'Ethan', 'Sophia', 'Mason',
        'Isabella', 'William', 'Mia', 'James', 'Charlotte', 'Benjamin', 'Amelia',
        'Lucas', 'Harper', 'Henry', 'Evelyn', 'Alexander', 'Abigail', 'Michael',
        'Emily', 'Daniel', 'Elizabeth', 'Matthew', 'Sofia', 'Jackson', 'Avery'
    ]
    
    LAST_NAMES = [
        'Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller',
        'Davis', 'Rodriguez', 'Martinez', 'Hernandez', 'Lopez', 'Gonzalez',
        'Wilson', 'Anderson', 'Thomas', 'Taylor', 'Moore', 'Jackson', 'Martin',
        'Lee', 'Perez', 'Thompson', 'White', 'Harris', 'Sanchez', 'Clark'
    ]
    
    SCHOOLS = [
        'Lincoln High School',
        'Roosevelt Academy',
        'Washington Preparatory',
        'Jefferson High School',
        'Kennedy Technical Institute',
        'Madison STEM Academy',
        'Monroe High School',
        'Adams College Prep',
        'Jackson Leadership Academy',
        'Franklin High School'
    ]
    
    CITIES = [
        ('Atlanta', 'Georgia'),
        ('Austin', 'Texas'),
        ('Charlotte', 'North Carolina'),
        ('Phoenix', 'Arizona'),
        ('Denver', 'Colorado'),
        ('Seattle', 'Washington'),
        ('Portland', 'Oregon'),
        ('Nashville', 'Tennessee'),
        ('Chicago', 'Illinois'),
        ('Boston', 'Massachusetts')
    ]
    
    INTERESTS = [
        'STEM', 'robotics', 'environmental science', 'computer science',
        'biomedical engineering', 'mathematics', 'physics', 'chemistry',
        'data science', 'artificial intelligence', 'renewable energy',
        'medical research', 'aerospace engineering', 'neuroscience'
    ]
    
    ACTIVITIES = [
        'founded the Science Club',
        'served as Student Government President',
        'led the Debate Team to state championships',
        'organized community STEM workshops',
        'captained the Robotics Team',
        'started a coding bootcamp for middle schoolers',
        'volunteered at a local hospital',
        'participated in Science Olympiad',
        'led environmental sustainability projects',
        'tutored underprivileged students in math',
        'competed in national chemistry competitions',
        'developed a mobile app for community service',
        'researched at a university lab',
        'published research in a youth science journal'
    ]
    
    AP_COURSES = [
        'AP Biology', 'AP Chemistry', 'AP Physics', 'AP Calculus AB',
        'AP Calculus BC', 'AP Computer Science', 'AP Statistics',
        'AP Environmental Science', 'AP US History', 'AP World History',
        'AP English Literature', 'AP Psychology'
    ]
    
    def generate_student(self, quality_tier: str = 'mixed') -> Dict[str, Any]:
        """
        Generate a realistic student application.
        
        Args:
            quality_tier: 'high', 'medium', 'low', or 'mixed' (random)
        """
        if quality_tier == 'mixed':
            quality_tier = random.choice(['high', 'high', 'medium', 'medium', 'low'])
        
        first_name = random.choice(self.FIRST_NAMES)
        last_name = random.choice(self.LAST_NAMES)
        name = f"{first_name} {last_name}"
        email = f"{first_name.lower()}.{last_name.lower()}{random.randint(1, 999)}@example.com"
        
        school = random.choice(self.SCHOOLS)
        city, state = random.choice(self.CITIES)
        
        # Quality-based attributes
        if quality_tier == 'high':
            gpa = round(random.uniform(3.7, 4.0), 2)
            ap_count = random.randint(5, 8)
            activities = random.sample(self.ACTIVITIES, random.randint(3, 5))
            interest = random.choice(self.INTERESTS)
            writing_quality = 'excellent'
        elif quality_tier == 'medium':
            gpa = round(random.uniform(3.3, 3.7), 2)
            ap_count = random.randint(2, 4)
            activities = random.sample(self.ACTIVITIES, random.randint(1, 3))
            interest = random.choice(self.INTERESTS)
            writing_quality = 'good'
        else:  # low
            gpa = round(random.uniform(2.8, 3.3), 2)
            ap_count = random.randint(0, 2)
            activities = random.sample(self.ACTIVITIES, random.randint(0, 2))
            interest = random.choice(self.INTERESTS)
            writing_quality = 'basic'
        
        ap_courses = random.sample(self.AP_COURSES, min(ap_count, len(self.AP_COURSES)))
        
        # Generate application text based on quality
        application_text = self._generate_application_text(
            name, school, city, state, gpa, ap_courses, activities, interest, writing_quality
        )
        
        return {
            'name': name,
            'email': email,
            'school': school,
            'city': city,
            'state': state,
            'gpa': gpa,
            'ap_courses': ap_courses,
            'activities': activities,
            'interest': interest,
            'application_text': application_text,
            'quality_tier': quality_tier
        }
    
    def _generate_application_text(self, name: str, school: str, city: str, state: str,
                                   gpa: float, ap_courses: List[str], activities: List[str],
                                   interest: str, quality: str) -> str:
        """Generate application essay based on quality level."""
        
        if quality == 'excellent':
            text = f"""My name is {name}, and I am a student at {school} in {city}, {state}. Throughout my academic journey, my passion for {interest} has been the driving force behind my achievements and aspirations.

I have maintained a {gpa} GPA while challenging myself with rigorous coursework including {', '.join(ap_courses[:3])}{',' if len(ap_courses) > 3 else ''} {f'and {len(ap_courses) - 3} additional AP courses' if len(ap_courses) > 3 else ''}. This academic foundation has prepared me exceptionally well for university-level work.

Beyond academics, I have demonstrated leadership and initiative through several impactful activities. {' I also '.join(activities[:2]) if len(activities) >= 2 else activities[0] if activities else 'I have been actively engaged in my school community'}. These experiences have taught me the value of collaboration, perseverance, and community impact.

My interest in {interest} stems from a genuine curiosity about how we can solve real-world problems through innovation and critical thinking. I am committed to pursuing advanced studies in this field and believe that higher education will provide me with the tools and knowledge to make meaningful contributions to society.

I am excited about the opportunity to bring my academic dedication, leadership experience, and passion for learning to the university level."""

        elif quality == 'good':
            text = f"""I am {name} from {school} in {city}, {state}. I have worked hard throughout high school to maintain a {gpa} GPA while taking challenging courses including {', '.join(ap_courses[:2]) if len(ap_courses) >= 2 else ap_courses[0] if ap_courses else 'honors classes'}.

I am particularly interested in {interest} and hope to study this field in college. {activities[0] if activities else 'I have been involved in various school activities'}, which has helped me develop important skills and discover my interests.

I believe I would be a good candidate for your program because I am dedicated to my studies and eager to learn. I am looking forward to the opportunities that college will provide to explore my interests further and prepare for my future career."""

        else:  # basic
            text = f"""My name is {name}. I go to {school} in {city}, {state}. I have a {gpa} GPA. {'I have taken ' + ap_courses[0] if ap_courses else 'I have taken regular courses'}.

I am interested in {interest} and want to study that in college. {'I have ' + activities[0].lower() if activities else 'I participate in school activities'}.

I think I would do well at your university. I am hardworking and want to continue my education."""
        
        return text
    
    def generate_batch(self, count: int = None) -> List[Dict[str, Any]]:
        """
        Generate a batch of test students.
        
        Args:
            count: Number of students (default: random 3-8)
        """
        if count is None:
            count = random.randint(3, 8)
        
        # Ensure variety in quality
        tiers = ['high'] * (count // 3) + ['medium'] * (count // 3) + ['low'] * (count - 2 * (count // 3))
        random.shuffle(tiers)
        
        students = []
        for tier in tiers:
            students.append(self.generate_student(tier))
        
        return students


# Global instance
test_data_generator = TestDataGenerator()
