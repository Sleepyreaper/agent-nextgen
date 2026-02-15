"""Generate realistic test student applications for agent testing."""

import random
from typing import List, Dict, Any, Tuple


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
    
    # Enhanced school data with metadata for Moana
    SCHOOLS = [
        {
            'name': 'Lincoln High School',
            'city': 'Atlanta',
            'state': 'Georgia',
            'type': 'Public',
            'ap_courses': 18,
            'ib_available': False,
            'stem_programs': 3,
            'median_income': 65000,
            'free_lunch_pct': 35.5,
            'total_enrollment': 1800
        },
        {
            'name': 'Roosevelt STEM Academy',
            'city': 'Marietta',
            'state': 'Georgia',
            'type': 'Public Magnet',
            'ap_courses': 24,
            'ib_available': True,
            'stem_programs': 5,
            'median_income': 85000,
            'free_lunch_pct': 18.2,
            'total_enrollment': 1200
        },
        {
            'name': 'Washington Preparatory School',
            'city': 'Savannah',
            'state': 'Georgia',
            'type': 'Private',
            'ap_courses': 22,
            'ib_available': True,
            'stem_programs': 4,
            'median_income': 95000,
            'free_lunch_pct': 5.0,
            'total_enrollment': 800
        },
        {
            'name': 'Jefferson High School',
            'city': 'Columbus',
            'state': 'Georgia',
            'type': 'Public',
            'ap_courses': 12,
            'ib_available': False,
            'stem_programs': 2,
            'median_income': 52000,
            'free_lunch_pct': 48.5,
            'total_enrollment': 2100
        },
        {
            'name': 'Kennedy Technical Institute',
            'city': 'Augusta',
            'state': 'Georgia',
            'type': 'Public Charter',
            'ap_courses': 8,
            'ib_available': False,
            'stem_programs': 6,
            'median_income': 58000,
            'free_lunch_pct': 42.0,
            'total_enrollment': 950
        }
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
    
    # Recommender templates
    RECOMMENDERS = [
        ('Dr. Sarah Jones', 'AP Chemistry Teacher', 'Science'),
        ('Mr. Michael Brown', 'Mathematics Department Chair', 'Math'),
        ('Ms. Emily Davis', 'Honors English Teacher', 'English'),
        ('Dr. Robert Wilson', 'Biology Teacher & Science Olympiad Coach', 'Science'),
        ('Mrs. Jennifer Martinez', 'AP Physics Teacher', 'Physics'),
        ('Mr. David Lee', 'Computer Science Teacher', 'Technology'),
        ('Ms. Amanda Taylor', 'Guidance Counselor', 'Counseling'),
        ('Dr. Christopher Anderson', 'AP Calculus Teacher', 'Math')
    ]
    
    # Grade subject pools
    CORE_SUBJECTS = [
        'English 9', 'English 10', 'English 11', 'English 12',
        'Algebra I', 'Geometry', 'Algebra II', 'Pre-Calculus',
        'Biology', 'Chemistry', 'Physics',
        'World History', 'US History', 'Government'
    ]
    
    def generate_transcript(self, name: str, school_data: Dict[str, Any], 
                           gpa: float, ap_courses: List[str], quality_tier: str) -> str:
        """Generate a realistic high school transcript."""
        school_name = school_data['name']
        city = school_data['city']
        state = school_data['state']
        
        # Generate grades based on quality tier
        if quality_tier == 'high':
            grade_pool = ['A', 'A', 'A', 'A', 'A-', 'A+']
        elif quality_tier == 'medium':
            grade_pool = ['A-', 'B+', 'B', 'A', 'B']
        else:
            grade_pool = ['B', 'B-', 'C+', 'B+', 'C']
        
        transcript = f"""
====================================
OFFICIAL HIGH SCHOOL TRANSCRIPT
====================================

Student Name: {name}
School: {school_name}
Location: {city}, {state}
Graduation Date: May 2026

====================================
ACADEMIC SUMMARY
====================================
Cumulative GPA: {gpa}/4.0 (Weighted)
Class Rank: {random.randint(5, 50)} of {random.randint(300, 500)}
Honor Roll: All Semesters

====================================
COURSEWORK BY YEAR
====================================

GRADE 9 (2022-2023)
-----------------------------------
English 9 Honors          | {random.choice(grade_pool)} | 1.0 credit
Algebra I                 | {random.choice(grade_pool)} | 1.0 credit
Biology                   | {random.choice(grade_pool)} | 1.0 credit
World History             | {random.choice(grade_pool)} | 1.0 credit
Spanish I                 | {random.choice(grade_pool)} | 1.0 credit
Physical Education        | {random.choice(grade_pool)} | 0.5 credit
Art I                     | {random.choice(grade_pool)} | 0.5 credit

GRADE 10 (2023-2024)
-----------------------------------
English 10 Honors         | {random.choice(grade_pool)} | 1.0 credit
Geometry Honors           | {random.choice(grade_pool)} | 1.0 credit
Chemistry                 | {random.choice(grade_pool)} | 1.0 credit
US History                | {random.choice(grade_pool)} | 1.0 credit
Spanish II                | {random.choice(grade_pool)} | 1.0 credit
Health                    | {random.choice(grade_pool)} | 0.5 credit
Music Theory              | {random.choice(grade_pool)} | 0.5 credit

GRADE 11 (2024-2025)
-----------------------------------
{"AP English Literature" if len(ap_courses) > 0 else "English 11"}   | {random.choice(grade_pool)} | 1.0 credit
{"AP Calculus AB" if "AP Calculus" in str(ap_courses) else "Algebra II"}   | {random.choice(grade_pool)} | 1.0 credit
{"AP Chemistry" if "AP Chemistry" in ap_courses else "Chemistry Honors"}     | {random.choice(grade_pool)} | 1.0 credit
{"AP US History" if "AP US History" in ap_courses else "US History"}   | {random.choice(grade_pool)} | 1.0 credit
Spanish III               | {random.choice(grade_pool)} | 1.0 credit

GRADE 12 (2025-2026 - In Progress)
-----------------------------------
{"AP Physics" if "AP Physics" in ap_courses else "Physics"}          | {random.choice(grade_pool)} | 1.0 credit
{"AP Calculus BC" if "AP Calculus BC" in ap_courses else "Pre-Calculus"}  | {random.choice(grade_pool)} | 1.0 credit
{"AP Computer Science" if "AP Computer Science" in ap_courses else "Computer Science"}  | {random.choice(grade_pool)} | 1.0 credit
Government / Economics    | {random.choice(grade_pool)} | 1.0 credit

====================================
STANDARDIZED TEST SCORES
====================================
SAT: {random.randint(1200, 1550) if quality_tier == 'high' else random.randint(1050, 1250)}
ACT: {random.randint(28, 34) if quality_tier == 'high' else random.randint(22, 27)}

====================================
AP EXAM SCORES
====================================
"""
        # Add AP scores if applicable
        if ap_courses:
            for course in ap_courses[:4]:  # Limit to 4 for brevity
                score = random.choice([5, 5, 4, 4, 3]) if quality_tier == 'high' else random.choice([4, 3, 3, 2])
                transcript += f"{course}: {score}\n"
        else:
            transcript += "No AP exams taken\n"
        
        transcript += """
====================================
ATTENDANCE RECORD
====================================
Days Absent: """ + str(random.randint(0, 5)) + """
Days Tardy: """ + str(random.randint(0, 3)) + """

This is an official transcript.
Issued: February 15, 2026
"""
        return transcript
    
    def generate_recommendation(self, name: str, quality_tier: str, 
                               activities: List[str]) -> Tuple[str, str, str]:
        """Generate a realistic recommendation letter. Returns (letter, recommender_name, recommender_role)."""
        recommender_name, recommender_role, subject = random.choice(self.RECOMMENDERS)
        
        activity = activities[0] if activities else 'participated actively in class'
        
        if quality_tier == 'high':
            letter = f"""To Whom It May Concern,

I am writing to give my highest recommendation for {name}, who has been one of the most exceptional students I have encountered in my 15 years of teaching.

{name} consistently demonstrates intellectual curiosity, academic rigor, and genuine passion for learning. In my {subject} class, they not only mastered complex material but frequently asked questions that pushed our discussions to new depths. Their analytical thinking and problem-solving abilities are truly remarkable.

Beyond academics, {name} {activity} and showed exceptional leadership qualities. They have the rare ability to inspire peers while remaining humble and collaborative. I have watched them mentor struggling students with patience and genuine care.

What sets {name} apart is their combination of intellectual capacity, work ethic, and character. They handle challenges with grace and view setbacks as learning opportunities. Their maturity and self-awareness are well beyond their years.

I recommend {name} without reservation. They will be an asset to any institution fortunate enough to have them.

Sincerely,
{recommender_name}
{recommender_role}
"""
        elif quality_tier == 'medium':
            letter = f"""To Whom It May Concern,

I am pleased to recommend {name} for your program. I have taught {name} for the past two years and have found them to be a dedicated and hardworking student.

{name} maintains good grades through consistent effort and participation. They are reliable, complete assignments on time, and contribute positively to class discussions. In my {subject} class, they demonstrated solid understanding of the material.

{name} {activity}, showing initiative and commitment to extracurricular involvement. They work well with peers and have good interpersonal skills.

I believe {name} would be a good fit for your program and recommend them for admission.

Sincerely,
{recommender_name}
{recommender_role}
"""
        else:  # low quality
            letter = f"""To Whom It May Concern,

I am writing to recommend {name}, who was a student in my {subject} class this year.

{name} attended class regularly and completed most assignments. They are friendly and get along well with other students.

I think {name} has potential and would benefit from the opportunities your program provides.

Sincerely,
{recommender_name}
{recommender_role}
"""
        
        return letter, recommender_name, recommender_role

    
    def generate_student(self, quality_tier: str = 'mixed') -> Dict[str, Any]:
        """
        Generate a realistic student application with all required data.
        
        Args:
            quality_tier: 'high', 'medium', 'low', or 'mixed' (random)
            
        Returns:
            Dictionary with complete student data including transcript and recommendation
        """
        if quality_tier == 'mixed':
            quality_tier = random.choice(['high', 'high', 'medium', 'medium', 'low'])
        
        first_name = random.choice(self.FIRST_NAMES)
        last_name = random.choice(self.LAST_NAMES)
        name = f"{first_name} {last_name}"
        email = f"{first_name.lower()}.{last_name.lower()}{random.randint(1, 999)}@example.com"
        
        # Select school with metadata
        school_data = random.choice(self.SCHOOLS)
        school_name = school_data['name']
        city = school_data['city']
        state = school_data['state']
        
        # Quality-based attributes
        if quality_tier == 'high':
            gpa = round(random.uniform(3.7, 4.0), 2)
            ap_count = min(random.randint(5, 8), school_data['ap_courses'])
            activities = random.sample(self.ACTIVITIES, random.randint(3, 5))
            interest = random.choice(self.INTERESTS)
            writing_quality = 'excellent'
        elif quality_tier == 'medium':
            gpa = round(random.uniform(3.3, 3.7), 2)
            ap_count = min(random.randint(2, 4), school_data['ap_courses'])
            activities = random.sample(self.ACTIVITIES, random.randint(1, 3))
            interest = random.choice(self.INTERESTS)
            writing_quality = 'good'
        else:  # low
            gpa = round(random.uniform(2.8, 3.3), 2)
            ap_count = min(random.randint(0, 2), school_data['ap_courses'])
            activities = random.sample(self.ACTIVITIES, random.randint(0, 2))
            interest = random.choice(self.INTERESTS)
            writing_quality = 'basic'
        
        ap_courses = random.sample(self.AP_COURSES, min(ap_count, len(self.AP_COURSES)))
        
        # Generate all components
        application_text = self._generate_application_text(
            name, school_name, city, state, gpa, ap_courses, activities, interest, writing_quality
        )
        
        transcript_text = self.generate_transcript(name, school_data, gpa, ap_courses, quality_tier)
        
        recommendation_text, recommender_name, recommender_role = self.generate_recommendation(
            name, quality_tier, activities
        )
        
        return {
            'name': name,
            'email': email,
            'school': school_name,
            'school_data': school_data,  # Complete school metadata for Moana
            'city': city,
            'state': state,
            'gpa': gpa,
            'ap_courses': ap_courses,
            'activities': activities,
            'interest': interest,
            'application_text': application_text,
            'transcript_text': transcript_text,  # For Rapunzel
            'recommendation_text': recommendation_text,  # For Mulan
            'recommender_name': recommender_name,
            'recommender_role': recommender_role,
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
            count: Number of students (default: 3)
        """
        if count is None:
            count = 3
        
        # Ensure variety in quality
        tiers = ['high'] * (count // 3) + ['medium'] * (count // 3) + ['low'] * (count - 2 * (count // 3))
        random.shuffle(tiers)
        
        students = []
        for tier in tiers:
            students.append(self.generate_student(tier))
        
        return students


# Global instance
test_data_generator = TestDataGenerator()
