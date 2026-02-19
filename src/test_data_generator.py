"""Generate realistic test student applications for agent testing."""

import random
from typing import List, Dict, Any, Tuple
from datetime import datetime, date, timedelta
import uuid


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
    
    # Enhanced school data with metadata for comprehensive testing
    SCHOOLS = [
        # Metro Atlanta - High Resource Schools
        {
            'name': 'North Springs Charter High School',
            'city': 'Sandy Springs',
            'state': 'Georgia',
            'type': 'Public Charter',
            'ap_courses': 28,
            'ib_available': True,
            'stem_programs': 5,
            'median_income': 102000,
            'free_lunch_pct': 12.5,
            'total_enrollment': 1650
        },
        {
            'name': 'Gwinnett School of Mathematics, Science and Technology',
            'city': 'Lawrenceville',
            'state': 'Georgia',
            'type': 'Public Magnet',
            'ap_courses': 32,
            'ib_available': False,
            'stem_programs': 8,
            'median_income': 95000,
            'free_lunch_pct': 8.2,
            'total_enrollment': 950
        },
        {
            'name': 'Westminster Schools',
            'city': 'Atlanta',
            'state': 'Georgia',
            'type': 'Private',
            'ap_courses': 26,
            'ib_available': True,
            'stem_programs': 6,
            'median_income': 185000,
            'free_lunch_pct': 3.0,
            'total_enrollment': 1900
        },
        # Suburban Georgia
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
            'name': 'Walton High School',
            'city': 'Marietta',
            'state': 'Georgia',
            'type': 'Public',
            'ap_courses': 22,
            'ib_available': False,
            'stem_programs': 4,
            'median_income': 92000,
            'free_lunch_pct': 15.8,
            'total_enrollment': 3200
        },
        # Urban Georgia - Diverse Resources
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
            'name': 'Grady High School',
            'city': 'Atlanta',
            'state': 'Georgia',
            'type': 'Public',
            'ap_courses': 20,
            'ib_available': True,
            'stem_programs': 4,
            'median_income': 72000,
            'free_lunch_pct': 28.4,
            'total_enrollment': 1950
        },
        # Coastal Georgia
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
            'name': 'Savannah Arts Academy',
            'city': 'Savannah',
            'state': 'Georgia',
            'type': 'Public Magnet',
            'ap_courses': 16,
            'ib_available': False,
            'stem_programs': 2,
            'median_income': 62000,
            'free_lunch_pct': 32.0,
            'total_enrollment': 750
        },
        # Central/Southwest Georgia
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
            'name': 'Columbus High School',
            'city': 'Columbus',
            'state': 'Georgia',
            'type': 'Public',
            'ap_courses': 14,
            'ib_available': False,
            'stem_programs': 3,
            'median_income': 55000,
            'free_lunch_pct': 42.0,
            'total_enrollment': 1650
        },
        # Northeast Georgia
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
        },
        {
            'name': 'Lakeside High School',
            'city': 'Evans',
            'state': 'Georgia',
            'type': 'Public',
            'ap_courses': 16,
            'ib_available': False,
            'stem_programs': 3,
            'median_income': 68000,
            'free_lunch_pct': 25.5,
            'total_enrollment': 2250
        },
        # Athens Area
        {
            'name': 'Clarke Central High School',
            'city': 'Athens',
            'state': 'Georgia',
            'type': 'Public',
            'ap_courses': 15,
            'ib_available': False,
            'stem_programs': 3,
            'median_income': 60000,
            'free_lunch_pct': 38.0,
            'total_enrollment': 1400
        },
        {
            'name': 'Athens Academy',
            'city': 'Athens',
            'state': 'Georgia',
            'type': 'Private',
            'ap_courses': 20,
            'ib_available': False,
            'stem_programs': 4,
            'median_income': 112000,
            'free_lunch_pct': 2.0,
            'total_enrollment': 1050
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
    
    # Comprehensive course catalog organized by level and type
    CORE_COURSES_BY_LEVEL = {
        9: {
            'english': ['English 9', 'English 9 Honors'],
            'math': ['Algebra I', 'Algebra I Honors', 'Geometry'],
            'science': ['Biology', 'Biology Honors', 'Physical Science'],
            'social_studies': ['World History', 'World History Honors'],
            'foreign_lang': ['Spanish I', 'Spanish I Honors', 'French I', 'Mandarin I'],
            'electives': ['Art I', 'Music I', 'Physical Education', 'Health', 'Technology Basics', 'Digital Media', 'Woodshop', 'Drama']
        },
        10: {
            'english': ['English 10', 'English 10 Honors'],
            'math': ['Geometry', 'Geometry Honors', 'Algebra II'],
            'science': ['Chemistry', 'Chemistry Honors', 'Biology Honors'],
            'social_studies': ['US History', 'US History Honors'],
            'foreign_lang': ['Spanish II', 'Spanish II Honors', 'French II', 'Mandarin II'],
            'electives': ['Art II', 'Music II', 'Physical Education', 'Health', 'Debate I', 'Robotics', 'Web Design', 'Photography', 'Band']
        },
        11: {
            'english': ['AP English Literature', 'AP English Language', 'English 11 Honors', 'English 11'],
            'math': ['AP Calculus AB', 'AP Statistics', 'Algebra II Honors', 'Pre-Calculus'],
            'science': ['AP Chemistry', 'AP Biology', 'AP Physics', 'Physics Honors', 'Physical Science'],
            'social_studies': ['AP US History', 'AP World History', 'AP European History', 'Government', 'Economics'],
            'foreign_lang': ['Spanish III', 'Spanish III Honors', 'AP Spanish Language', 'French III', 'Mandarin III'],
            'electives': ['AP Computer Science A', 'Computer Science Honors', 'Debate II', 'Mock Trial', 'Robotics II', 'Environmental Science', 'Psychology', 'Media Studies', 'Orchestra']
        },
        12: {
            'english': ['AP Literature', 'AP Language', 'English 12 Honors', 'Creative Writing', 'Journalism'],
            'math': ['AP Calculus BC', 'AP Statistics', 'Pre-Calculus Honors', 'Linear Algebra'],
            'science': ['AP Physics C', 'AP Environmental Science', 'AP Biology', 'Chemistry Honors', 'Anatomy and Physiology'],
            'social_studies': ['AP US Government', 'AP Economics', 'AP Human Geography', 'Sociology', 'History Seminar'],
            'foreign_lang': ['AP Spanish Language', 'Spanish IV', 'AP French Language', 'Mandarin IV', 'Chinese Culture'],
            'electives': ['AP Computer Science AB', 'AI and Robotics', 'Data Science', 'Debate III', 'Coding for Social Good', 'Neuroscience', 'Bioethics', 'String Ensemble']
        }
    }

    
    def _generate_birthdate(self, grade_level: int) -> date:
        """
        Generate a realistic birthdate based on grade level for 2025-2026 school year.
        
        Current date: February 2026 (middle of 2025-2026 school year)
        High school enrollment for 2025-2026:
        - Freshman (9th): Born 2010-2011, Ages 14-15
        - Sophomore (10th): Born 2009-2010, Ages 15-16
        - Junior (11th): Born 2008-2009, Ages 16-17
        - Senior (12th): Born 2007-2008, Ages 17-18
        
        Args:
            grade_level: 9, 10, 11, or 12
            
        Returns:
            date object for student's birthdate
        """
        # Map grade level to birth year based on 2025-2026 school year
        birth_year_map = {
            9: [2010, 2011],   # Freshman: Ages 14-15
            10: [2009, 2010],  # Sophomore: Ages 15-16
            11: [2008, 2009],  # Junior: Ages 16-17
            12: [2007, 2008]   # Senior: Ages 17-18
        }
        
        birth_year = random.choice(birth_year_map.get(grade_level, [2009, 2010]))
        
        # Random month and day
        birth_month = random.randint(1, 12)
        if birth_month == 2:
            # February - account for leap years
            max_day = 29 if birth_year % 4 == 0 else 28
        elif birth_month in [4, 6, 9, 11]:
            max_day = 30
        else:
            max_day = 31
        
        birth_day = random.randint(1, max_day)
        return date(birth_year, birth_month, birth_day)
    
    def _generate_semester_courses(self, grade_level: int, semester: int, 
                                  gpa: float, quality_tier: str, ap_courses: List[str]) -> List[Tuple[str, str, str]]:
        """
        Generate courses for a specific semester.
        
        Args:
            grade_level: 9, 10, 11, or 12
            semester: 1 or 2
            gpa: Student's overall GPA
            quality_tier: 'high', 'medium', or 'low'
            ap_courses: List of AP courses the student is taking
            
        Returns:
            List of (course_name, grade, credits) tuples (minimum 5 courses per semester)
        """
        if quality_tier == 'high':
            grade_pool = ['A', 'A', 'A+', 'A', 'A-', 'A']
        elif quality_tier == 'medium':
            grade_pool = ['A-', 'B+', 'B', 'A', 'B', 'B+']
        else:
            grade_pool = ['B', 'B-', 'C+', 'B+', 'C', 'C+']
        
        courses = []
        course_data = self.CORE_COURSES_BY_LEVEL[grade_level]
        
        # Ensure at least 5 courses per semester
        # Required: 1 English, 1 Math, 1 Science, 1 Social Studies
        # + at least 1 elective, possibly a language course
        
        # English course
        english_courses = course_data['english']
        courses.append((random.choice(english_courses), random.choice(grade_pool), '1.0'))
        
        # Math course
        math_courses = course_data['math']
        courses.append((random.choice(math_courses), random.choice(grade_pool), '1.0'))
        
        # Science course
        science_courses = course_data['science']
        courses.append((random.choice(science_courses), random.choice(grade_pool), '1.0'))
        
        # Social Studies course
        ss_courses = course_data['social_studies']
        courses.append((random.choice(ss_courses), random.choice(grade_pool), '1.0'))
        
        # Foreign language (not every semester)
        if random.random() > 0.2:
            lang_courses = course_data['foreign_lang']
            courses.append((random.choice(lang_courses), random.choice(grade_pool), '1.0'))
        
        # Electives - add 2-3 more courses
        elective_courses = course_data['electives']
        num_electives = random.randint(2, 3)
        for _ in range(num_electives):
            elective = random.choice(elective_courses)
            credit = '1.0' if elective not in ['Physical Education', 'Health'] else '0.5'
            courses.append((elective, random.choice(grade_pool), credit))
        
        # Ensure we have at least 5 distinct courses per semester
        # Deduplicate by name
        seen = set()
        unique_courses = []
        for course_tuple in courses:
            if course_tuple[0] not in seen:
                unique_courses.append(course_tuple)
                seen.add(course_tuple[0])
        
        # If we lost any, add more electives
        while len(unique_courses) < 5:
            elective = random.choice(elective_courses)
            if elective not in seen:
                credit = '1.0' if elective not in ['Physical Education', 'Health'] else '0.5'
                unique_courses.append((elective, random.choice(grade_pool), credit))
                seen.add(elective)
        
        return unique_courses[:8]  # Cap at 8 courses per semester for realism
    
    def generate_transcript(self, name: str, school_data: Dict[str, Any], 
                           gpa: float, ap_courses: List[str], quality_tier: str,
                           birthdate: date = None) -> str:
        """Generate a realistic high school transcript with comprehensive course listings."""
        school_name = school_data['name']
        city = school_data['city']
        state = school_data['state']
        
        # Determine grade level from birthdate if available
        grade_level = 12  # Default to senior
        if birthdate:
            age_in_june_2026 = (date(2026, 6, 1) - birthdate).days // 365
            if age_in_june_2026 < 17:
                grade_level = 10  # Sophomore
            elif age_in_june_2026 < 18:
                grade_level = 11  # Junior
            else:
                grade_level = 12  # Senior
        
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
Date of Birth: {birthdate.strftime('%B %d, %Y') if birthdate else 'Not provided'}
Current Grade: {grade_level}
School Name: {school_name}
Location: {city}, {state}
Graduation Date: May {2026 + (12 - grade_level)}

====================================
ACADEMIC SUMMARY
====================================
Cumulative GPA: {gpa}/4.0 (Weighted)
Class Rank: {random.randint(5, 50)} of {random.randint(300, 500)}
Honor Roll: {random.randint(5, 8)} consecutive semesters

====================================
COURSEWORK BY YEAR
====================================
"""
        
        # Generate courses for all years the student has completed
        start_grade = max(9, grade_level - 3)  # Show up to 4 years of history
        
        for year_offset, academic_year_grade in enumerate(range(start_grade, grade_level + 1)):
            current_year = 2023 + year_offset
            next_year = current_year + 1
            
            if academic_year_grade == grade_level:
                year_label = f"GRADE {academic_year_grade} ({current_year}-{next_year} - In Progress)"
            else:
                year_label = f"GRADE {academic_year_grade} ({current_year}-{next_year})"
            
            transcript += f"\n{year_label}\n"
            transcript += "-" * 50 + "\n"
            
            # Fall semester (Semester 1)
            transcript += "FALL SEMESTER\n"
            fall_courses = self._generate_semester_courses(
                academic_year_grade, 1, gpa, quality_tier, ap_courses
            )
            for course_name, grade, credits in fall_courses:
                transcript += f"{course_name:<40} | {grade:>2s} | {credits} credit\n"
            
            # Spring semester (Semester 2)
            transcript += "\nSPRING SEMESTER\n"
            spring_courses = self._generate_semester_courses(
                academic_year_grade, 2, gpa, quality_tier, ap_courses
            )
            for course_name, grade, credits in spring_courses:
                transcript += f"{course_name:<40} | {grade:>2s} | {credits} credit\n"
            
            # GPA for this year
            year_gpa = round(gpa + random.uniform(-0.1, 0.1), 2)
            year_gpa = max(2.0, min(4.0, year_gpa))  # Clamp between 2.0 and 4.0
            transcript += f"\nGPA for Grade {academic_year_grade}: {year_gpa}/4.0\n"
        
        transcript += f"""
====================================
STANDARDIZED TEST SCORES
====================================
SAT: {random.randint(1200, 1550) if quality_tier == 'high' else random.randint(1050, 1250)}
ACT: {random.randint(28, 34) if quality_tier == 'high' else random.randint(22, 27)}
"""
        
        # Add AP exam scores
        transcript += "\n====================================\nAP EXAM SCORES\n====================================\n"
        if ap_courses:
            for course in ap_courses[:6]:  # Show up to 6 AP scores
                score = random.choice([5, 5, 4, 4, 3]) if quality_tier == 'high' else random.choice([4, 3, 3, 2])
                # Convert course name to likely AP exam name
                ap_exam_name = course.replace("AP ", "")
                transcript += f"{ap_exam_name}: {score}\n"
        else:
            transcript += "No AP exams taken\n"
        
        transcript += f"""
====================================
ATTENDANCE RECORD
====================================
Days Absent: {random.randint(0, 5)}
Days Tardy: {random.randint(0, 3)}

====================================
EXTRACURRICULAR ACTIVITIES
====================================
- Consistent participation in academic clubs and competitions
- {random.choice(['Leadership positions held', 'Community service hours: ' + str(random.randint(20, 100)), 'Athletic team participation'])}
- {random.choice(['Science competition participation', 'Debate team member', 'Robotics club member', 'Student government'])}

====================================
NOTES
====================================
This is an official transcript from {school_name}.
Issued: February 18, 2026
"""
        return transcript

    
    def generate_recommendation(self, name: str, quality_tier: str, 
                               activities: List[str]) -> Tuple[str, str, str]:
        """Generate a single realistic recommendation letter. Returns (letter, recommender_name, recommender_role)."""
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
    
    def generate_multiple_recommendations(self, name: str, quality_tier: str, 
                                         activities: List[str], count: int = 3) -> List[Dict[str, str]]:
        """
        Generate multiple recommendation letters (3-5) from different recommenders.
        
        Args:
            name: Student name
            quality_tier: 'high', 'medium', or 'low'
            activities: List of student activities
            count: Number of recommendations to generate (default 3, max 5)
            
        Returns:
            List of dicts with keys: 'text', 'recommender_name', 'recommender_role'
        """
        recommendations = []
        used_recommenders = set()
        count = min(count, 5)  # Cap at 5 recommendations
        
        for _ in range(count):
            # Ensure we don't reuse the same recommender
            attempts = 0
            while attempts < 20:
                letter, rec_name, rec_role = self.generate_recommendation(name, quality_tier, activities)
                if rec_name not in used_recommenders:
                    used_recommenders.add(rec_name)
                    recommendations.append({
                        'text': letter,
                        'recommender_name': rec_name,
                        'recommender_role': rec_role
                    })
                    break
                attempts += 1
        
        return recommendations

    
    def generate_student(self, quality_tier: str = 'mixed', used_names: set = None, 
                        grade_level: int = None) -> Dict[str, Any]:
        """
        Generate a realistic student application with comprehensive data.
        
        Now generates 3-5 recommendations per student (more for higher quality).
        Based on 2025-2026 school year enrollment (February 2026).
        
        Args:
            quality_tier: 'high', 'medium', 'low', or 'mixed' (random)
            used_names: Set of already-used names to avoid duplicates
            grade_level: 9, 10, 11, or 12 (freshman, sophomore, junior, senior). 
                        If None, defaults to 10-12 (typical college applicants).
            
        Returns:
            Dictionary with complete student data:
            - birthdate (based on 2025-2026 enrollment)
            - grade_level (9-12)
            - transcript_text (full 4-year transcript)
            - recommendations (list of 3-5 recommendation dicts)
            - school_data (comprehensive school metadata)
            - All other application materials
        """
        if quality_tier == 'mixed':
            quality_tier = random.choice(['high', 'high', 'medium', 'medium', 'low'])
        
        # Determine grade level (default to 10-12 for typical college applicants)
        if grade_level is None:
            grade_level = random.choice([10, 10, 11, 11, 12, 12])  # Weighted toward juniors/seniors
        
        # Generate realistic birthdate for the grade level
        birthdate = self._generate_birthdate(grade_level)
        
        used_names = used_names or set()
        name = None
        for _ in range(10):
            first_name = random.choice(self.FIRST_NAMES)
            last_name = random.choice(self.LAST_NAMES)
            candidate = f"{first_name} {last_name}"
            if candidate not in used_names:
                name = candidate
                break

        if not name:
            first_name = random.choice(self.FIRST_NAMES)
            last_name = random.choice(self.LAST_NAMES)
            middle_initial = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
            name = f"{first_name} {middle_initial}. {last_name}"

        used_names.add(name)

        unique_token = uuid.uuid4().hex[:6]
        email = f"{name.lower().replace(' ', '.').replace('.', '')}.{unique_token}@example.com"
        
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
        
        transcript_text = self.generate_transcript(name, school_data, gpa, ap_courses, quality_tier, birthdate)
        
        # Generate 3-5 recommendations based on quality tier
        num_recommendations = 5 if quality_tier == 'high' else 4 if quality_tier == 'medium' else 3
        recommendations = self.generate_multiple_recommendations(name, quality_tier, activities, num_recommendations)
        
        # Keep backward compatibility with single recommendation
        primary_rec = recommendations[0] if recommendations else {
            'text': '', 'recommender_name': '', 'recommender_role': ''
        }
        
        return {
            'name': name,
            'email': email,
            'school': school_name,
            'school_data': school_data,  # Complete school metadata for Moana
            'city': city,
            'state': state,
            'birthdate': birthdate,  # Student's date of birth for age/grade verification
            'grade_level': grade_level,  # Current grade level (9, 10, 11, or 12)
            'gpa': gpa,
            'ap_courses': ap_courses,
            'activities': activities,
            'interest': interest,
            'application_text': application_text,
            'transcript_text': transcript_text,  # For Rapunzel
            'recommendations': recommendations,  # MAIN: List of 3-5 recommendation dicts
            'recommendation_text': primary_rec['text'],  # DEPRECATED: For backward compat
            'recommender_name': primary_rec['recommender_name'],  # DEPRECATED
            'recommender_role': primary_rec['recommender_role'],  # DEPRECATED
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
        used_names = set()
        for tier in tiers:
            students.append(self.generate_student(tier, used_names=used_names))
        
        return students


# Global instance
test_data_generator = TestDataGenerator()
