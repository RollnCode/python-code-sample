class RelevantResultsView(FormView):
    """View renders a list of users filtered by complex coditions."""
    form_class = RelevantCandidatesResultsForm
    template_name = 'relevant_candidates_results_form.html'

    def relevant_results_sql(self, context):
        filters = {
            'role_id__in': context.get('role'),
        }
        exclude_unavailable = {}
        exclude_unknown = {}

        required_tech_skills = context.get('required_tech_skills', [])
        if required_tech_skills:
            filters.update({'skill_ids__contains': required_tech_skills})

        required_specialties = context.get('required_specialties', [])
        if required_specialties:
            filters.update({'specialty_names__contains': required_specialties})

        joined_after = context.get('joined_after')
        if joined_after:
            month, day, year = map(int, joined_after.split('/'))
            date = datetime.date(year, month, day)
            filters.update({'date_joined__date__gt': date})

        desired_tech_skills = context.get('desired_tech_skills', [])
        desired_specialties = context.get('desired_specialties', [])

        if context.get('exclude_unavailable'):
            exclude_unavailable['available'] = False

        if context.get('exclude_unknown'):
            exclude_unknown['available__isnull'] = True

        if context.get('member'):
            filters.update({'member': True})

        desired_tech_skills = desired_tech_skills or []
        desired_specialties = desired_specialties or []

        qs = MainView.objects.only(
            'user_id', 'full_name', 'role', 'primary_area', 'experience_level', 'current_job_title', 'year_exp',
            'industry', 'avg_tenure', 'specialty_names', 'skill_names', 'linkedin_url', 'resume_name', 'resume_url',
            'urls', 'date_joined', 'role_id', 'skill_ids', 'specialty_ids', 'available', 'member',
        ).filter(
            **filters
        ).exclude(
            Q(**exclude_unavailable) | Q(**exclude_unknown)
        ).annotate(
            length_tech_skills=Value(len(desired_tech_skills), output_field=FloatField()),
            length_desired_specialties=Value(len(desired_specialties), output_field=FloatField()),
            desired_skills_count=RawSQL(
                "SELECT count(*) FROM unnest(skill_ids) id WHERE id = ANY(%s::int[]) GROUP BY user_id",
                [desired_tech_skills]
            ),
            desired_specialties_count=RawSQL(
                "SELECT count(*) FROM unnest(specialty_names) name WHERE name = ANY(%s::text[]) GROUP BY user_id",
                [desired_specialties]
            ),
            desired_skills_score=Case(
                # if desired_tech_skills there but desired_skills_count return null, then 0
                # if desired_tech_skills is missing, then 0.5
                When(length_tech_skills=0, then=Value(0.5)),
                When(desired_skills_count__isnull=True, then=Value(0)),
                default=(
                    Cast(F('desired_skills_count'), FloatField())
                    / Value(len(desired_tech_skills), output_field=FloatField())
                    * Value(0.5)
                ),
                output_field=FloatField()
            ),
            desired_specialties_score=Case(
                # if desired_specialties there but desired_specialties_count return null, then 0
                # if desired_specialties is missing, then 0.3
                When(length_desired_specialties=0, then=Value(0.3)),
                When(desired_specialties_count__isnull=True, then=0),
                default=(
                    Cast(F('desired_specialties_count'), FloatField())
                    / Value(len(desired_specialties), output_field=FloatField())
                    * Value(0.3)
                ),
                output_field=FloatField()
            ),
            experience_score=Case(When(
                experience_level_id__in=context.get('desired_experience'),
                then=Value(0.2)),
                default=Value(0.0),
                output_field=FloatField()),
            match_score=Round(
                (F('desired_skills_score') + F('desired_specialties_score') + F('experience_score')) * 100,
                output_field=IntegerField()
            ),
        ).order_by('-match_score', 'full_name')
        return qs

    def post(self, request, *args, **kwargs):
        post = {}
        for key, value in dict(request.POST.lists()).items():
            post[key] = [x.replace("\n", "") for x in value]
        if 'csrfmiddlewaretoken' in post:
            post['csrfmiddlewaretoken'] = post['csrfmiddlewaretoken'][0]
        if 'joined_after' in post:
            post['joined_after'] = post['joined_after'][0]
        if 'available' in post:
            post['available'] = post['available'][0]
        if 'member' in post:
            post['member'] = post['member'][0]

        form = RelevantCandidatesResultsForm(post)
        if form.is_valid():
            relevant_data = dict(form.data)
            if "csrfmiddlewaretoken" in relevant_data:
                del relevant_data["csrfmiddlewaretoken"]
            json_relevant_data = json.dumps(relevant_data)
            export_form = ExportForm(initial={'selection_keys': json_relevant_data})
            form_selection = SaveAnonymousSelectionForm(initial={'selection_keys': json_relevant_data})

            context = {}

            for val in form:
                context.update({
                    val.name: val.value() if not isinstance(val.value(), list) else list(map(str, val.value()))
                })

            results = self.relevant_results_sql(context)
            table = RelevantResultsTable(results)
            role_id = tuple(form.cleaned_data['role'].values_list('id', flat=True))
            filtered_skills = get_specialties_by_role(role_id)
            form.fields["required_specialties"].queryset = Specialty.objects.filter(
                skill_name__in=filtered_skills).distinct('skill_name')
            form.fields["desired_specialties"].queryset = Specialty.objects.filter(
                skill_name__in=filtered_skills).distinct('skill_name')
            return render(request, self.template_name, {'form': form,
                                                        'relevant_results': table,
                                                        'hidden': True,
                                                        'export_form': export_form,
                                                        'form_selection': form_selection
                                                        })
        return render(request, self.template_name, {'form': form})

